"""Buyback API (M1.4a, ADR-025): a universe equity's authorizations, actual repurchases and net
share reduction, kept apart (02 §5), as known at a time. Read-only.

- Announcements: authorization, plan and remaining-amount statements from 8-Ks (stored by
  `sec.eight_k`, current extractor version) and from the issuer's press releases (title and
  snippet, read on request), grouped into events (domain/buyback.py). Each keeps its sentence
  and link as evidence.
- As tagged: the latest XBRL repurchase_authorized and repurchase_remaining of 10-Q/10-K, which
  only corroborate (they are known at filing acceptance and mean different things per company).
- Per period: repurchases, intensity, funding, SBC offset, debt-funded flag, net share reduction
  and diluted share change, each with its inputs and filings.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from autotrading.api.data_health import SessionDep
from autotrading.api.instruments import FactView, issuer_chain
from autotrading.api.research import KnownAt, ResearchPeriod
from autotrading.api.valuation import (
    InputOut,
    MetricOut,
    filing_forms,
    input_out,
    known_at_or_now,
    market_view,
    metric_out,
    universe_equity,
)
from autotrading.db.models import FilingBuybackStatement, Instrument, NewsItem, NewsMention
from autotrading.domain.buyback import (
    BUYBACK_METRICS,
    AnnouncementSource,
    Section,
    buyback_record,
    events,
)
from autotrading.domain.buyback_announcements import EXTRACTOR_VERSION, statement
from autotrading.domain.valuation import Input, Unit

router = APIRouter(tags=["buybacks"])

TAGGED_METRICS = ("repurchase_authorized", "repurchase_remaining")
HISTORY_YEARS = 6  # closes for five fiscal year ends and the latest quarter


class AnnouncementSourceOut(BaseModel):
    channel: Literal["sec_8k", "press_release"]
    sentence: str  # the issuer's words, at most 300 characters
    url: str
    published_at: datetime
    stated_date: date | None
    accession: str | None
    document_type: str | None  # 8-K, EX-99.1, ...
    title: str | None  # press release


class AnnouncementEvent(BaseModel):
    kind: Literal["new", "increase", "plan", "remaining"]
    amount: Decimal  # USD
    remaining_amount: Decimal | None
    day: date  # stated, else the first publication day in New York
    first_published_at: datetime
    sources: list[AnnouncementSourceOut]


class BuybackRow(BaseModel):
    metric_id: str
    section: Section
    unit: Unit
    cells: list[MetricOut]  # one per period, in the order of `periods`


class BuybacksOut(BaseModel):
    ticker: str
    known_at: datetime
    extractor_version: str
    announcements: list[AnnouncementEvent]  # newest first
    tagged_authorized: InputOut | None  # latest XBRL authorization, as the filing tags it
    tagged_remaining: InputOut | None
    periods: list[ResearchPeriod]
    rows: list[BuybackRow]


def announcement_sources(
    session: Session, instrument: Instrument, chain: list[UUID], at: datetime
) -> list[AnnouncementSource]:
    """Statements of 8-Ks by the issuer chain and of the issuer's press releases, known at T."""
    filed = [
        AnnouncementSource(
            channel="sec_8k",
            kind=row.kind,
            amount=row.amount,
            remaining_amount=row.remaining_amount,
            stated_date=row.stated_date,
            sentence=row.sentence,
            url=row.source_url,
            published_at=row.published_at,
            accession=row.accession_number,
            document_type=row.document_type,
        )
        for row in session.scalars(
            select(FilingBuybackStatement).where(
                FilingBuybackStatement.entity_id.in_(chain),
                FilingBuybackStatement.published_at <= at,
                FilingBuybackStatement.extractor_version == EXTRACTOR_VERSION,
            )
        )
    ]
    released = []
    for item in session.scalars(
        select(NewsItem)
        .join(NewsMention, NewsMention.news_item_id == NewsItem.id)
        .where(
            NewsMention.instrument_id == instrument.id,
            NewsItem.kind == "press_release",
            NewsItem.published_at <= at,
        )
        .distinct()
    ):
        for text in (item.title, item.snippet):
            found = statement(text) if text else None
            if found is not None:
                released.append(
                    AnnouncementSource(
                        channel="press_release",
                        kind=found.kind,
                        amount=found.amount,
                        remaining_amount=found.remaining_amount,
                        stated_date=found.stated_date,
                        sentence=found.sentence,
                        url=item.url,
                        published_at=item.published_at,
                        title=item.title,
                    )
                )
    return filed + released


def _latest(facts: list[FactView], metric: str) -> Input[FactView] | None:
    found = [f for f in facts if f.metric_id == metric and f.period_start is None]
    if not found:
        return None
    latest = max(found, key=lambda f: (f.period_end, f.reported_at))
    return Input(
        metric, latest.value, None, latest.period_end, (latest,), "as tagged in the filing"
    )


@router.get("/instruments/{ticker}/buybacks")
def instrument_buybacks(ticker: str, session: SessionDep, known_at: KnownAt = None) -> BuybacksOut:
    instrument = universe_equity(session, ticker)
    assert instrument.entity_id is not None
    at = known_at_or_now(session, known_at)
    chain = issuer_chain(session, instrument.entity_id)
    view = market_view(
        session,
        instrument,
        chain.order,
        at,
        (*BUYBACK_METRICS, *TAGGED_METRICS),
        bars_since=datetime(at.year - HISTORY_YEARS, 1, 1, tzinfo=UTC),
    )
    record = buyback_record(view.facts, view.closes, at, view.splits)
    tagged = {m: _latest(view.facts, m) for m in TAGGED_METRICS}
    found_events = events(announcement_sources(session, instrument, chain.order, at), at)
    forms = filing_forms(
        session,
        [
            *(f for *_, values in record.rows for v in values for i in v.inputs for f in i.sources),
            *(f for i in tagged.values() if i is not None for f in i.sources),
        ],
    )
    return BuybacksOut(
        ticker=ticker.upper(),
        known_at=at,
        extractor_version=EXTRACTOR_VERSION,
        announcements=[
            AnnouncementEvent(
                kind=e.kind,  # type: ignore[arg-type]
                amount=e.amount,
                remaining_amount=e.remaining_amount,
                day=e.day,
                first_published_at=e.first_published_at,
                sources=[
                    AnnouncementSourceOut(
                        channel=s.channel,
                        sentence=s.sentence,
                        url=s.url,
                        published_at=s.published_at,
                        stated_date=s.stated_date,
                        accession=s.accession,
                        document_type=s.document_type,
                        title=s.title,
                    )
                    for s in e.sources
                ],
            )
            for e in found_events
        ],
        tagged_authorized=input_out(i, forms) if (i := tagged["repurchase_authorized"]) else None,
        tagged_remaining=input_out(i, forms) if (i := tagged["repurchase_remaining"]) else None,
        periods=[
            ResearchPeriod(kind=w.kind, period_start=w.start, period_end=w.end)
            for w in record.periods
        ],
        rows=[
            BuybackRow(
                metric_id=metric,
                section=section,
                unit=unit,
                cells=[metric_out(v, forms) for v in values],
            )
            for section, metric, unit, values in record.rows
        ],
    )
