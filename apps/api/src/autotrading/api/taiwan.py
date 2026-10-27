"""The Taiwan universe (M3.7, ADR-039 TW11-TW13): what the TWSE OpenAPI published, as known at
T. Nothing is computed beyond reading the stored rows: percentiles against the instrument's
own monthly history, balance changes between two stored sessions, and the reference price
check (TW9).

- `GET /taiwan`: every Taiwan universe instrument's latest stored session, the Taipei session
  state, the sessions no run caught, the source attribution.
- `GET /taiwan/instruments/{code}`: one instrument: its closes (raw, and on T's split basis),
  the exchange's P/E, P/B and dividend yield with percentiles, the margin and short balances,
  its dividends, the reference price check, and (M3.7b, ADR-040) the institutional investors'
  net buying and the foreign holding from FinMind, a tier 2 source named on the block.

Research only: no strategy, signal, alert or portfolio reads Taiwan (TW12). Every value cites
its file, publication time and run; every page shows the Open Government Data attribution.
"""

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Literal
from urllib.parse import parse_qs, urlparse
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from autotrading.adapters.finmind.client import ATTRIBUTION as FINMIND_ATTRIBUTION
from autotrading.adapters.finmind.client import DATASET_NAMES as FINMIND_DATASET_NAMES
from autotrading.adapters.finmind.client import SOURCE_ID as FINMIND_SOURCE_ID
from autotrading.adapters.twse.client import (
    DATASET_NAMES,
    DAY,
    EX_RIGHTS,
    MARGIN,
    VALUATION,
)
from autotrading.api.data_health import SessionDep
from autotrading.api.research import KnownAt
from autotrading.api.valuation import known_at_or_now
from autotrading.db.models import DividendEvent, ExchangeMeasure, Instrument, PriceBar, SplitEvent
from autotrading.domain.fair_value import relative
from autotrading.domain.finmind import FLOW_UNITS, SHAREHOLDING_UNITS
from autotrading.domain.market_calendar import MarketCalendar
from autotrading.domain.markets import TW
from autotrading.domain.splits import Split, adjust
from autotrading.domain.twse import reference_gap
from autotrading.domain.valuation import Close, close_basis
from autotrading.ingestion.schedule import market_calendar
from autotrading.repositories.exchange_measures import measures
from autotrading.repositories.labels import label
from autotrading.repositories.prices import daily_bars, instruments_by_symbol
from autotrading.repositories.universe import taiwan_universe

router = APIRouter(tags=["taiwan"])

PROVIDER = "臺灣證券交易所"
LICENSE = "此開放資料依政府資料開放授權條款 (Open Government Data License) 進行公眾釋出"
LICENSE_URL = "https://data.gov.tw/license"
HISTORY = timedelta(days=400)  # a year of sessions on the page
VALUATION_MEASURES = ("exchange_pe_ratio", "exchange_pb_ratio", "exchange_dividend_yield")
MARGIN_MEASURES = (
    "margin_balance",
    "margin_balance_previous",
    "margin_limit",
    "short_balance",
    "short_balance_previous",
    "short_limit",
    "margin_purchase",
    "margin_sale",
    "short_sale",
    "short_covering",
    "margin_short_offset",
)
FLOWS_REASON = (
    "Data unavailable: no institutional investor row stored yet (FinMind, daily at 21:30 SGT; "
    "the TWSE OpenAPI does not publish them per stock)."
)
FLOW_MEASURES = tuple(FLOW_UNITS)
HOLDING_MEASURES = tuple(SHAREHOLDING_UNITS)
FLOW_GROUPS = ("inst_foreign_net", "inst_trust_net", "inst_dealer_net", "inst_total_net")
FLOW_WINDOW = 20  # sessions summed on the page
FINMIND_TERMS_URL = "https://finmind.github.io/Pricing/"
RESEARCH_ONLY = (
    "Research only: no strategy, signal, alert or paper portfolio reads Taiwan (ADR-039 TW12). "
    "History starts with the first collected session; values are what TWSE published, as known "
    "at the time shown. Not advice."
)


class SourceRef(BaseModel):
    dataset: str
    source_url: str
    published_at: datetime
    ingested_at: datetime
    ingestion_run_id: UUID | None
    raw_payload_sha256: str | None
    license_status: str
    confidence: Decimal


class SupplementaryAttribution(BaseModel):
    provider: str
    text: str  # the line the source's terms require
    terms_url: str


class Attribution(BaseModel):
    provider: str
    year: int
    datasets: list[str]
    license: str
    license_url: str
    text: str
    supplementary: list[SupplementaryAttribution] = []  # FinMind when its data is shown


class TaiwanSession(BaseModel):
    open: bool
    last_close: datetime
    next_open: datetime
    timezone: str
    calendar_covered_until: date


class TaiwanRow(BaseModel):
    code: str
    name: str
    name_zh: str
    instrument_type: Literal["equity", "etf"]
    session: date | None  # the latest stored session known at T
    close: Decimal | None
    feed_status: str | None  # end_of_day, or fixture for recorded test data (DEMO DATA)
    change: Decimal | None
    history_since: date | None
    sessions: int


class TaiwanListOut(BaseModel):
    known_at: datetime
    benchmark: str
    ranked_on: str
    market_session: TaiwanSession
    latest_session: date | None
    missing_sessions: list[date]  # calendar sessions since the first one with no stored close
    rows: list[TaiwanRow]
    attribution: Attribution
    detail: str = RESEARCH_ONLY


class PricePoint(BaseModel):
    session: date
    close: Decimal
    adjusted_close: Decimal  # on T's split basis (stock dividends)


class PriceBlock(BaseModel):
    session: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    change: Decimal | None
    reference: Decimal | None  # close - change: TWSE's reference price of the session
    volume: int  # shares
    trade_value: Decimal | None  # TWD
    feed_status: str  # end_of_day, or fixture for recorded test data (DEMO DATA)
    history: list[PricePoint]
    history_since: date
    sessions: int
    source: SourceRef


class ValuationMeasure(BaseModel):
    measure_id: str
    value: Decimal | None
    reason: Literal["not_meaningful"] | None  # P/E with a loss: TWSE leaves it blank
    detail: str | None
    percentile: Decimal | None
    median: Decimal | None
    observations: int  # month ends of the instrument's own history
    since: date | None


class ValuationBlock(BaseModel):
    session: date
    measures: list[ValuationMeasure]
    percentile_min_observations: int
    source: SourceRef


class MarginBlock(BaseModel):
    session: date
    unit: str  # lots of 1,000 shares
    values: dict[str, Decimal]
    margin_change: Decimal | None  # today's balance less the previous one
    short_change: Decimal | None
    margin_usage: Decimal | None  # balance / limit, percent
    short_to_margin: Decimal | None  # short balance / margin balance, percent (券資比)
    note: str | None
    source: SourceRef


class CorporateAction(BaseModel):
    ex_date: date
    kind: Literal["cash_dividend", "stock_dividend"]
    value: Decimal  # TWD per share, or shares per share
    source: SourceRef


class ReferenceCheck(BaseModel):
    session: date
    reference: Decimal
    expected: Decimal
    previous_session: date
    previous_close: Decimal
    note: str


class FlowGroup(BaseModel):
    measure_id: str  # inst_foreign_net, inst_trust_net, inst_dealer_net, inst_total_net
    net_last: Decimal  # shares, the latest session
    net_window: Decimal  # shares, summed over the last `sessions_in_window` sessions
    sessions_in_window: int
    unit: str


class FlowPoint(BaseModel):
    session: date
    foreign_net: Decimal
    total_net: Decimal


class FlowsBlock(BaseModel):
    status: Literal["ok", "unavailable"]
    reason: str | None = None
    session: date | None = None
    groups: list[FlowGroup] = []
    history: list[FlowPoint] = []  # the last sessions, oldest first
    holding_session: date | None = None
    foreign_shares: Decimal | None = None
    shares_issued: Decimal | None = None
    foreign_ratio: Decimal | None = None  # percent
    foreign_limit_ratio: Decimal | None = None  # percent
    source: SourceRef | None = None
    holding_source: SourceRef | None = None
    attribution: str | None = None  # 資料來源：FinMind


class TaiwanInstrumentOut(BaseModel):
    code: str
    name: str
    name_zh: str
    about_zh: str
    sector_zh: str | None
    instrument_type: Literal["equity", "etf"]
    currency: str
    known_at: datetime
    market_session: TaiwanSession
    price: PriceBlock | None
    valuation: ValuationBlock | None
    margin: MarginBlock | None
    actions: list[CorporateAction]
    reference_gaps: list[ReferenceCheck]
    missing_sessions: list[date]
    flows: FlowsBlock
    attribution: Attribution
    detail: str = RESEARCH_ONLY


def attribution(at: datetime, *, finmind: bool = False) -> Attribution:
    year = at.astimezone(TW.zone).year
    datasets = [DATASET_NAMES[p] for p in (DAY, VALUATION, MARGIN, EX_RIGHTS)]
    return Attribution(
        provider=PROVIDER,
        year=year,
        datasets=datasets,
        license=LICENSE,
        license_url=LICENSE_URL,
        text=f"{PROVIDER} {year} {'、'.join(datasets)}；{LICENSE}，{LICENSE_URL}",
        supplementary=[
            SupplementaryAttribution(
                provider="FinMind", text=FINMIND_ATTRIBUTION, terms_url=FINMIND_TERMS_URL
            )
        ]
        if finmind
        else [],
    )


def taiwan_session(calendar: MarketCalendar, at: datetime) -> TaiwanSession:
    return TaiwanSession(
        open=calendar.is_open(at),
        last_close=calendar.last_close(at),
        next_open=calendar.next_open(at),
        timezone=TW.zone.key,
        calendar_covered_until=calendar.covered_until,
    )


def _dataset_name(row: PriceBar | ExchangeMeasure | DividendEvent | SplitEvent, path: str) -> str:
    """The file a row came from: a TWSE OpenAPI file, or the FinMind dataset its URL names."""
    if row.source_id == FINMIND_SOURCE_ID:
        dataset = parse_qs(urlparse(row.source_url).query).get("dataset", [""])[0]
        return FINMIND_DATASET_NAMES.get(dataset, f"FinMind {dataset}")
    return DATASET_NAMES.get(path, path)


def _ref(row: PriceBar | ExchangeMeasure | DividendEvent | SplitEvent, path: str) -> SourceRef:
    return SourceRef(
        dataset=_dataset_name(row, path),
        source_url=row.source_url,
        published_at=row.published_at,
        ingested_at=row.ingested_at,
        ingestion_run_id=row.ingestion_run_id,
        raw_payload_sha256=row.raw_payload_sha256,
        license_status=row.license_status,
        confidence=Decimal(row.confidence),
    )


def _bars(session: Session, instrument_id: UUID, at: datetime, since: datetime) -> list[PriceBar]:
    return daily_bars(session, instrument_id, "raw", since=since, until=at, known_at=at)


def _missing(calendar: MarketCalendar, stored: set[date], at: datetime) -> list[date]:
    """Calendar sessions between the first and the last stored session with no stored close."""
    if not stored:
        return []
    first, last = min(stored), max(stored)
    return [s.day for s in calendar.sessions_between(first, last) if s.day not in stored]


def _instrument(session: Session, code: str) -> tuple[UUID, Instrument]:
    if code not in taiwan_universe().codes:
        raise HTTPException(status_code=404, detail=f"{code} is not in the Taiwan universe")
    ids = instruments_by_symbol(session, [code], TW.namespace)
    if code not in ids:
        raise HTTPException(status_code=404, detail=f"{code} has no data yet (make twse-refresh)")
    return ids[code], session.get_one(Instrument, ids[code])


def _kind(instrument: Instrument) -> Literal["equity", "etf"]:
    return "etf" if instrument.instrument_type == "etf" else "equity"


@router.get("/taiwan")
def taiwan_list(session: SessionDep, known_at: KnownAt = None) -> TaiwanListOut:
    at = known_at_or_now(session, known_at)
    universe = taiwan_universe()
    calendar = market_calendar(TW.exchange)
    ids = instruments_by_symbol(session, list(universe.codes), TW.namespace)
    rows = []
    stored: set[date] = set()
    finmind = False
    for code in universe.codes:
        found = label(code)
        if code not in ids:
            rows.append(
                TaiwanRow(
                    code=code,
                    name=found.name,
                    name_zh=found.zh,
                    instrument_type="etf" if code in universe.etfs else "equity",
                    session=None,
                    close=None,
                    feed_status=None,
                    change=None,
                    history_since=None,
                    sessions=0,
                )
            )
            continue
        bars = _bars(session, ids[code], at, at - HISTORY)
        stored |= {b.bar_date for b in bars}
        finmind = finmind or any(b.source_id == FINMIND_SOURCE_ID for b in bars)
        last = bars[-1] if bars else None
        change = None
        if last is not None:
            values = measures(
                session,
                ids[code],
                ["price_change"],
                known_at=at,
                since=last.bar_date,
                until=last.bar_date,
            )
            change = values[0].value if values else None
        rows.append(
            TaiwanRow(
                code=code,
                name=found.name,
                name_zh=found.zh,
                instrument_type="etf" if code in universe.etfs else "equity",
                session=last.bar_date if last else None,
                close=last.close if last else None,
                feed_status=last.feed_status if last else None,
                change=change,
                history_since=bars[0].bar_date if bars else None,
                sessions=len(bars),
            )
        )
    return TaiwanListOut(
        known_at=at,
        benchmark=universe.benchmark,
        ranked_on=universe.ranked_on,
        market_session=taiwan_session(calendar, at),
        latest_session=max(stored) if stored else None,
        missing_sessions=_missing(calendar, stored, at),
        rows=rows,
        attribution=attribution(at, finmind=finmind),
    )


@router.get("/taiwan/instruments/{code}")
def taiwan_instrument(
    code: str, session: SessionDep, known_at: KnownAt = None
) -> TaiwanInstrumentOut:
    code = code.upper()
    instrument_id, instrument = _instrument(session, code)
    at = known_at_or_now(session, known_at)
    calendar = market_calendar(TW.exchange)
    found = label(code)
    bars = _bars(session, instrument_id, at, at - HISTORY)
    splits_rows = session.scalars(
        select(SplitEvent).where(
            SplitEvent.instrument_id == instrument_id, SplitEvent.published_at <= at
        )
    ).all()
    dividends = session.scalars(
        select(DividendEvent).where(
            DividendEvent.instrument_id == instrument_id, DividendEvent.published_at <= at
        )
    ).all()
    splits = [Split(s.ex_date, s.old_rate, s.new_rate, TW.zone) for s in splits_rows]
    stored_measures = measures(
        session,
        instrument_id,
        [
            "price_change",
            "trade_value",
            *VALUATION_MEASURES,
            *MARGIN_MEASURES,
            *FLOW_MEASURES,
            *HOLDING_MEASURES,
        ],
        known_at=at,
    )
    finmind = any(b.source_id == FINMIND_SOURCE_ID for b in bars) or any(
        m.source_id == FINMIND_SOURCE_ID for m in stored_measures
    )
    by_session: dict[date, dict[str, ExchangeMeasure]] = {}
    for m in stored_measures:
        by_session.setdefault(m.session_date, {})[m.measure_id] = m
    return TaiwanInstrumentOut(
        code=code,
        name=found.name,
        name_zh=found.zh,
        about_zh=found.about_zh,
        sector_zh=found.sector_zh,
        instrument_type=_kind(instrument),
        currency=instrument.currency,
        known_at=at,
        market_session=taiwan_session(calendar, at),
        price=_price(bars, by_session, splits, at),
        valuation=_valuation(by_session),
        margin=_margin(by_session),
        actions=[
            *(
                CorporateAction(
                    ex_date=d.ex_date,
                    kind="cash_dividend",
                    value=d.rate,
                    source=_ref(d, EX_RIGHTS),
                )
                for d in dividends
            ),
            *(
                CorporateAction(
                    ex_date=s.ex_date,
                    kind="stock_dividend",
                    value=s.new_rate / s.old_rate - 1,
                    source=_ref(s, EX_RIGHTS),
                )
                for s in splits_rows
            ),
        ],
        reference_gaps=_reference_checks(
            code, _kind(instrument), bars, by_session, dividends, splits_rows, calendar
        ),
        missing_sessions=_missing(calendar, {b.bar_date for b in bars}, at),
        flows=_flows(by_session),
        attribution=attribution(at, finmind=finmind),
    )


def _flows(by_session: dict[date, dict[str, ExchangeMeasure]]) -> FlowsBlock:
    """The institutional investors' net buying (FinMind) of the latest session and summed over
    the last sessions, and the latest foreign holding."""
    sessions = [d for d in sorted(by_session) if "inst_total_net" in by_session[d]]
    if not sessions:
        return FlowsBlock(status="unavailable", reason=FLOWS_REASON)
    window = sessions[-FLOW_WINDOW:]
    latest = by_session[sessions[-1]]
    groups = [
        FlowGroup(
            measure_id=measure_id,
            net_last=latest[measure_id].value,
            net_window=sum((by_session[d][measure_id].value for d in window), Decimal(0)),
            sessions_in_window=len(window),
            unit=FLOW_UNITS[measure_id],
        )
        for measure_id in FLOW_GROUPS
        if measure_id in latest
    ]
    holding_sessions = [d for d in sorted(by_session) if "foreign_ratio" in by_session[d]]
    holding = by_session[holding_sessions[-1]] if holding_sessions else {}
    return FlowsBlock(
        status="ok",
        session=sessions[-1],
        groups=groups,
        history=[
            FlowPoint(
                session=d,
                foreign_net=by_session[d]["inst_foreign_net"].value,
                total_net=by_session[d]["inst_total_net"].value,
            )
            for d in window
            if "inst_foreign_net" in by_session[d]
        ],
        holding_session=holding_sessions[-1] if holding_sessions else None,
        foreign_shares=holding["foreign_shares"].value if "foreign_shares" in holding else None,
        shares_issued=holding["shares_issued"].value if "shares_issued" in holding else None,
        foreign_ratio=holding["foreign_ratio"].value if "foreign_ratio" in holding else None,
        foreign_limit_ratio=(
            holding["foreign_limit_ratio"].value if "foreign_limit_ratio" in holding else None
        ),
        source=_ref(latest["inst_total_net"], ""),
        holding_source=_ref(holding["foreign_ratio"], "") if "foreign_ratio" in holding else None,
        attribution=FINMIND_ATTRIBUTION,
    )


def _price(
    bars: list[PriceBar],
    by_session: dict[date, dict[str, ExchangeMeasure]],
    splits: list[Split],
    at: datetime,
) -> PriceBlock | None:
    if not bars:
        return None
    last = bars[-1]
    day = by_session.get(last.bar_date, {})
    change = day["price_change"].value if "price_change" in day else None

    def adjusted(bar: PriceBar) -> Decimal:
        close = Close(bar.bar_date, bar.close, bar.feed_status, bar.published_at, TW.zone)
        moved = adjust("close", bar.close, close_basis(close), at, splits)
        return moved.value if moved else bar.close

    return PriceBlock(
        session=last.bar_date,
        open=last.open,
        high=last.high,
        low=last.low,
        close=last.close,
        change=change,
        reference=last.close - change if change is not None else None,
        volume=last.volume,
        trade_value=day["trade_value"].value if "trade_value" in day else None,
        feed_status=last.feed_status,
        history=[
            PricePoint(session=b.bar_date, close=b.close, adjusted_close=adjusted(b)) for b in bars
        ],
        history_since=bars[0].bar_date,
        sessions=len(bars),
        source=_ref(last, DAY),
    )


def _valuation(by_session: dict[date, dict[str, ExchangeMeasure]]) -> ValuationBlock | None:
    sessions = [d for d in sorted(by_session) if "exchange_pb_ratio" in by_session[d]]
    if not sessions:
        return None
    latest = sessions[-1]
    # the last value of each Taipei month (TW11)
    month_end: dict[tuple[int, int], date] = {}
    for d in sessions:
        month_end[(d.year, d.month)] = d
    minimum = 12
    out = []
    for measure_id in VALUATION_MEASURES:
        row = by_session[latest].get(measure_id)
        history = [
            (d, by_session[d][measure_id].value)
            for d in month_end.values()
            if measure_id in by_session[d]
        ]
        found = relative(measure_id, row.value if row else None, history)
        enough = found.observations >= minimum
        out.append(
            ValuationMeasure(
                measure_id=measure_id,
                value=row.value if row else None,
                reason="not_meaningful"
                if row is None and measure_id == "exchange_pe_ratio"
                else None,
                detail=row.detail if row else None,
                percentile=found.percentile if enough else None,
                median=found.median if enough else None,
                observations=found.observations,
                since=found.since,
            )
        )
    return ValuationBlock(
        session=latest,
        measures=out,
        percentile_min_observations=minimum,
        source=_ref(by_session[latest]["exchange_pb_ratio"], VALUATION),
    )


def _margin(by_session: dict[date, dict[str, ExchangeMeasure]]) -> MarginBlock | None:
    sessions = [d for d in sorted(by_session) if "margin_balance" in by_session[d]]
    if not sessions:
        return None
    latest = by_session[sessions[-1]]
    values = {k: v.value for k, v in latest.items() if k in MARGIN_MEASURES}
    hundred = Decimal(100)

    def ratio(top: str, bottom: str) -> Decimal | None:
        if not values.get(bottom):
            return None
        return (values[top] / values[bottom] * hundred).quantize(Decimal("0.01"))

    def change(today: str, before: str) -> Decimal | None:
        return values[today] - values[before] if today in values and before in values else None

    return MarginBlock(
        session=sessions[-1],
        unit=latest["margin_balance"].unit,
        values=values,
        margin_change=change("margin_balance", "margin_balance_previous"),
        short_change=change("short_balance", "short_balance_previous"),
        margin_usage=ratio("margin_balance", "margin_limit"),
        short_to_margin=ratio("short_balance", "margin_balance"),
        note=latest["margin_balance"].detail,
        source=_ref(latest["margin_balance"], MARGIN),
    )


def _reference_checks(
    code: str,
    kind: Literal["equity", "etf"],
    bars: list[PriceBar],
    by_session: dict[date, dict[str, ExchangeMeasure]],
    dividends: Sequence[DividendEvent],
    splits: Sequence[SplitEvent],
    calendar: MarketCalendar,
) -> list[ReferenceCheck]:
    """Each stored session whose TWSE reference price no recorded action explains (TW9); a
    pair with a lost session between is not checked (its reference is that session's close)."""
    cash = {d.ex_date: d.rate for d in dividends}
    stock = {s.ex_date: s.new_rate / s.old_rate - 1 for s in splits}
    out = []
    for before, bar in pairwise(bars):
        change = by_session.get(bar.bar_date, {}).get("price_change")
        between = calendar.sessions_between(
            before.bar_date + timedelta(days=1), bar.bar_date - timedelta(days=1)
        )
        if change is None or between:
            continue
        gap = reference_gap(
            code,
            bar.bar_date,
            bar.close,
            change.value,
            before.bar_date,
            before.close,
            etf=kind == "etf",
            cash=cash.get(bar.bar_date, Decimal(0)),
            stock_ratio=stock.get(bar.bar_date, Decimal(0)),
        )
        if gap is not None:
            out.append(
                ReferenceCheck(
                    session=gap.session,
                    reference=gap.reference,
                    expected=gap.expected,
                    previous_session=gap.previous_session,
                    previous_close=gap.previous_close,
                    note=gap.note(),
                )
            )
    return out
