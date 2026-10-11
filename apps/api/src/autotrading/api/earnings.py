"""Earnings API (M1.5, ADR-026): a universe equity's earnings events, and the Earnings dashboard,
as known at a time. Read-only.

- Events: 8-Ks with Item 2.02 since 2021 (E1) by the issuer chain, at their acceptance time.
- Report and actuals (E2): the matched 10-Q/10-K once it is public at T, and its quarter's
  revenue, EPS, margins and FCF against the quarter before and a year earlier.
- Guidance (E3): the statements `sec.earnings_release` stored at the current extractor version;
  a release it read without any is "none", one it has not read is "not read".
- Reaction (E4): the stock's return minus SPY's from the last close before the event.
- Consensus: no provider (OD-3); always null with "Data unavailable" (errata E6).
"""

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from autotrading.adapters.sec.parsing import filing_index_url
from autotrading.adapters.sec.refresh import EARNINGS_READER, EIGHT_K_SINCE, reader_accessions
from autotrading.api.data_health import SessionDep
from autotrading.api.instruments import FactView, issuer_chain, universe_equities
from autotrading.api.research import KnownAt
from autotrading.api.valuation import (
    InputOut,
    filing_forms,
    input_out,
    known_at_or_now,
    market_view,
    universe_equity,
)
from autotrading.db.models import Filing, FilingGuidanceStatement, Instrument, PriceBar
from autotrading.domain.earnings import (
    ACTUAL_METRICS,
    Actual,
    ActualMetric,
    DayBar,
    QuarterValue,
    Reaction,
    Report,
    Timing,
    actual_series,
    actuals,
    match_report,
    prepare,
    reaction_from,
    timing,
)
from autotrading.domain.guidance import GUIDANCE_VERSION
from autotrading.ingestion.schedule import market_calendar
from autotrading.repositories.prices import daily_bars, instruments_by_symbol

router = APIRouter(tags=["earnings"])

BENCHMARK = "SPY"
EVENT_ITEM = "2.02"
BARS_BEFORE = timedelta(days=45)  # 20 sessions of volume before the first event
RECENT = timedelta(days=730)  # the dashboard's event list
NO_CONSENSUS = "Data unavailable: no consensus provider (OD-3)"
GuidanceStatus = Literal["extracted", "none", "not_read"]


class GuidanceOut(BaseModel):
    metric: str  # revenue, revenue_growth, eps, gross_margin, operating_margin, net_margin
    low: Decimal
    high: Decimal
    unit: Literal["USD", "USD/shares", "percent"]
    period: str  # as written
    adjusted: bool
    sentence: str  # the issuer's words, at most 300 characters
    url: str
    document_type: str


class ReactionWindowOut(BaseModel):
    label: str
    sessions_after: int
    day: date | None
    stock_return: Decimal | None  # percent
    benchmark_return: Decimal | None  # percent
    relative: Decimal | None  # percentage points
    detail: str | None


class ReactionOut(BaseModel):
    benchmark: str
    base_day: date | None
    base_close: Decimal | None
    windows: list[ReactionWindowOut]
    volume_ratio: Decimal | None  # x
    volume_detail: str | None
    detail: str | None


class QuarterValueOut(BaseModel):
    period_start: date | None
    period_end: date | None
    value: Decimal | None
    detail: str | None
    inputs: list[InputOut]  # the current quarter's; earlier quarters' are at their own event


class ActualOut(BaseModel):
    metric: ActualMetric
    unit: str
    current: QuarterValueOut
    prior_quarter: QuarterValueOut
    year_ago: QuarterValueOut
    change_qoq: Decimal | None
    change_yoy: Decimal | None
    change_unit: Literal["percent", "percentage points"]


class ReportOut(BaseModel):
    accession: str
    form: str
    published_at: datetime
    period_end: date
    url: str


class ConsensusOut(BaseModel):
    eps: None = None
    revenue: None = None
    surprise: None = None
    detail: str = NO_CONSENSUS


class EarningsEventOut(BaseModel):
    accession: str
    form: str
    url: str  # the filing's EDGAR index
    accepted_at: datetime  # the EDGAR acceptance time (01 §23)
    accepted_at_precision: str  # exact; day when only the date is known
    timing: Timing
    items: list[str]
    report: ReportOut | None
    report_detail: str | None  # why there are no actuals yet
    actuals: list[ActualOut]
    guidance_status: GuidanceStatus
    guidance: list[GuidanceOut]
    reaction: ReactionOut
    consensus: ConsensusOut


class EarningsOut(BaseModel):
    ticker: str
    known_at: datetime
    guidance_version: str
    events: list[EarningsEventOut]  # newest first


class EarningsSummary(BaseModel):
    ticker: str
    name: str
    accession: str
    accepted_at: datetime
    timing: Timing
    period_end: date | None  # of the matched report, once public
    revenue_yoy: Decimal | None  # percent
    eps_yoy: Decimal | None  # percent
    day0_relative: Decimal | None  # percentage points against SPY
    guidance_status: GuidanceStatus
    guidance_count: int
    consensus: ConsensusOut


class EarningsDashboard(BaseModel):
    known_at: datetime
    latest: list[EarningsSummary]  # each company's latest event, by ticker
    recent: list[EarningsSummary]  # every event of the last two years, newest first


# ---------- reads ----------


def _events(session: Session, chain: Sequence[UUID], at: datetime) -> list[Filing]:
    return [
        f
        for f in session.scalars(
            select(Filing)
            .where(
                Filing.entity_id.in_(chain),
                Filing.form == "8-K",
                Filing.filing_date >= EIGHT_K_SINCE,
                Filing.published_at <= at,
            )
            .order_by(Filing.published_at.desc())
        )
        if EVENT_ITEM in (f.items or "").split(",")
    ]


def _reports(session: Session, chain: Sequence[UUID]) -> list[Report]:
    return [
        Report(
            f.accession_number,
            f.form,
            f.published_at,
            f.report_date,
            filing_index_url(f.cik, f.accession_number),
        )
        for f in session.scalars(
            select(Filing).where(
                Filing.entity_id.in_(chain),
                Filing.form.in_(("10-Q", "10-K")),
                Filing.report_date.is_not(None),
            )
        )
        if f.report_date is not None
    ]


def _bars(rows: Sequence[PriceBar]) -> list[DayBar]:
    return [DayBar(b.bar_date, b.close, b.volume, b.feed_status, b.published_at) for b in rows]


def _benchmark(session: Session, since: datetime, at: datetime) -> list[DayBar]:
    instrument = instruments_by_symbol(session, [BENCHMARK]).get(BENCHMARK)
    if instrument is None:
        return []
    return _bars(daily_bars(session, instrument, "raw", since=since, until=at, known_at=at))


def _guidance(
    session: Session, chain: Sequence[UUID], accessions: Sequence[str], at: datetime
) -> dict[str, list[GuidanceOut]]:
    out: dict[str, list[GuidanceOut]] = {}
    seen: set[tuple[str, str, Decimal, Decimal, bool]] = set()
    for row in session.scalars(
        select(FilingGuidanceStatement)
        .where(
            FilingGuidanceStatement.entity_id.in_(chain),
            FilingGuidanceStatement.accession_number.in_(accessions),
            FilingGuidanceStatement.extractor_version == GUIDANCE_VERSION,
            FilingGuidanceStatement.published_at <= at,
        )
        .order_by(FilingGuidanceStatement.document_type, FilingGuidanceStatement.id)
    ):
        key = (row.accession_number, row.metric, row.low, row.high, row.adjusted)
        if key in seen:  # the same outlook in the release and a CFO commentary
            continue
        seen.add(key)
        out.setdefault(row.accession_number, []).append(
            GuidanceOut(
                metric=row.metric,
                low=row.low,
                high=row.high,
                unit=row.unit,  # type: ignore[arg-type]
                period=row.period_text,
                adjusted=row.adjusted,
                sentence=row.sentence,
                url=row.source_url,
                document_type=row.document_type,
            )
        )
    return out


def _value_out(
    value: QuarterValue[FactView], forms: dict[str, str], with_inputs: bool = True
) -> QuarterValueOut:
    return QuarterValueOut(
        period_start=value.period_start,
        period_end=value.period_end,
        value=value.value,
        detail=value.detail,
        inputs=[input_out(i, forms) for i in value.inputs] if with_inputs else [],
    )


def _actual_out(actual: Actual[FactView], forms: dict[str, str]) -> ActualOut:
    # The quarter before and the year-earlier quarter are the current quarters of earlier
    # events, which carry their inputs: repeating them here would multiply the response.
    return ActualOut(
        metric=actual.metric,
        unit=actual.unit,
        current=_value_out(actual.current, forms),
        prior_quarter=_value_out(actual.prior_quarter, forms, with_inputs=False),
        year_ago=_value_out(actual.year_ago, forms, with_inputs=False),
        change_qoq=actual.change_qoq,
        change_yoy=actual.change_yoy,
        change_unit=actual.change_unit,
    )


def _reaction_out(found: Reaction) -> ReactionOut:
    return ReactionOut(
        benchmark=BENCHMARK,
        base_day=found.base_day,
        base_close=found.base_close,
        windows=[
            ReactionWindowOut(
                label=w.label,
                sessions_after=w.sessions_after,
                day=w.day,
                stock_return=w.stock_return,
                benchmark_return=w.benchmark_return,
                relative=w.relative,
                detail=w.detail,
            )
            for w in found.windows
        ],
        volume_ratio=found.volume_ratio,
        volume_detail=found.volume_detail,
        detail=found.detail,
    )


def company_events(
    session: Session, instrument: Instrument, at: datetime, since: datetime | None = None
) -> list[EarningsEventOut]:
    """Every earnings event of one company known at T (accepted from `since`), newest first."""
    assert instrument.entity_id is not None
    chain = issuer_chain(session, instrument.entity_id)
    filings = [
        f for f in _events(session, chain.order, at) if since is None or f.published_at >= since
    ]
    if not filings:
        return []
    bars_since = min(f.published_at for f in filings) - BARS_BEFORE
    view = market_view(session, instrument, chain.order, at, ACTUAL_METRICS, bars_since=bars_since)
    benchmark = _benchmark(session, bars_since, at)
    sessions = frozenset(b.day for b in benchmark if b.feed_status == "end_of_day")
    calendar = market_calendar()
    closes = prepare(_bars(view.bars), benchmark, at, calendar, view.splits)
    series = actual_series(view.facts)
    reports = _reports(session, chain.order)
    read = {
        a
        for cik in {f.cik for f in filings}
        for a in reader_accessions(session, EARNINGS_READER, cik)
    }
    guidance = _guidance(session, chain.order, [f.accession_number for f in filings], at)
    matched = []
    for filing in filings:
        report = match_report(filing.published_at, reports)
        known = report is not None and report.published_at <= at
        found = actuals(series, report.period_end, at, view.splits) if known and report else []
        matched.append((filing, report, known, found))
    forms = filing_forms(  # one query for every event's filings
        session,
        (f for *_, found in matched for a in found for i in a.current.inputs for f in i.sources),
    )
    events = []
    for filing, report, known, found in matched:
        stated = guidance.get(filing.accession_number, [])
        status: GuidanceStatus = (
            "extracted" if stated else "none" if filing.accession_number in read else "not_read"
        )
        events.append(
            EarningsEventOut(
                accession=filing.accession_number,
                form=filing.form,
                url=filing_index_url(filing.cik, filing.accession_number),
                accepted_at=filing.published_at,
                accepted_at_precision=filing.published_at_precision,
                timing=timing(filing.published_at, calendar, sessions),
                items=[i for i in (filing.items or "").split(",") if i],
                report=ReportOut(
                    accession=report.accession,
                    form=report.form,
                    published_at=report.published_at,
                    period_end=report.period_end,
                    url=report.url,
                )
                if known and report
                else None,
                report_detail=None
                if known
                else f"{report.form} for the period to {report.period_end} not yet public"
                if report
                else "no matching 10-Q or 10-K yet",
                actuals=[_actual_out(a, forms) for a in found],
                guidance_status=status,
                guidance=stated,
                reaction=_reaction_out(reaction_from(filing.published_at, closes)),
                consensus=ConsensusOut(),
            )
        )
    return events


def _summary(ticker: str, name: str, event: EarningsEventOut) -> EarningsSummary:
    by_metric = {a.metric: a for a in event.actuals}
    day0 = next((w for w in event.reaction.windows if w.sessions_after == 0), None)
    return EarningsSummary(
        ticker=ticker,
        name=name,
        accession=event.accession,
        accepted_at=event.accepted_at,
        timing=event.timing,
        period_end=event.report.period_end if event.report else None,
        revenue_yoy=by_metric["revenue"].change_yoy if "revenue" in by_metric else None,
        eps_yoy=by_metric["eps_diluted"].change_yoy if "eps_diluted" in by_metric else None,
        day0_relative=day0.relative if day0 else None,
        guidance_status=event.guidance_status,
        guidance_count=len(event.guidance),
        consensus=ConsensusOut(),
    )


@router.get("/instruments/{ticker}/earnings")
def instrument_earnings(ticker: str, session: SessionDep, known_at: KnownAt = None) -> EarningsOut:
    instrument = universe_equity(session, ticker)
    at = known_at_or_now(session, known_at)
    return EarningsOut(
        ticker=ticker.upper(),
        known_at=at,
        guidance_version=GUIDANCE_VERSION,
        events=company_events(session, instrument, at),
    )


@router.get("/earnings")
def earnings_dashboard(session: SessionDep, known_at: KnownAt = None) -> EarningsDashboard:
    at = known_at_or_now(session, known_at)
    latest, recent = [], []
    for ticker, instrument, entity in universe_equities(session):
        events = company_events(session, instrument, at, since=at - RECENT)
        if events:
            latest.append(_summary(ticker, entity.name, events[0]))
        recent += [_summary(ticker, entity.name, e) for e in events]
    return EarningsDashboard(
        known_at=at,
        latest=latest,
        recent=sorted(recent, key=lambda s: s.accepted_at, reverse=True),
    )
