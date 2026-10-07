"""Valuation API (M1.2, ADR-022): market cap, enterprise value and multiples of a universe
equity as known at a time, each with its inputs, their dates and sources. Read-only.

Facts are those `/instruments/{ticker}/fundamentals` shows at the same time (ADR-012, ADR-014);
the price is the last daily raw close known then (domain/valuation.py decides whether a
valuation may use it).
"""

from collections.abc import Iterable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import AwareDatetime, BaseModel
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from autotrading.api.data_health import SessionDep
from autotrading.api.instruments import FactView, FilingRef, issuer_chain, open_sec
from autotrading.db.models import Filing, FinancialFact, Identifier, Instrument, SplitEvent
from autotrading.domain.fundamentals import merge_by_precedence
from autotrading.domain.splits import Split
from autotrading.domain.valuation import Close, Input, PriceInput, select_price, valuation
from autotrading.repositories.facts import as_of_query
from autotrading.repositories.prices import daily_bars

router = APIRouter(tags=["valuation"])

VALUATION_METRICS = (
    "revenue",
    "operating_income",
    "depreciation_amortization",
    "operating_cash_flow",
    "capex",
    "eps_diluted",
    "shares_outstanding",
    "shares_outstanding_cover",
    "long_term_debt_noncurrent",
    "long_term_debt_current",
    "commercial_paper",
    "cash",
    "stockholders_equity",
)
PRICE_LOOKBACK = timedelta(days=40)  # far enough back to call an old close stale


class SourceOut(BaseModel):
    metric_id: str
    source_concept: str | None
    value: Decimal
    period_start: date | None
    period_end: date
    filing: FilingRef


class InputOut(BaseModel):
    name: str  # a metric id, or "price"
    value: Decimal | None
    period_start: date | None
    period_end: date | None
    note: str | None
    sources: list[SourceOut]  # the reported facts behind it


class MetricOut(BaseModel):
    metric_id: str
    unit: Literal["USD", "USD/shares", "x", "percent"]
    value: Decimal | None
    reason: Literal["unavailable", "not_meaningful"] | None
    detail: str | None
    inputs: list[InputOut]


class PriceOut(BaseModel):
    status: Literal["ok", "fixture", "demo", "stale", "none"]
    detail: str
    day: date | None
    close: Decimal | None
    feed_status: str | None
    published_at: datetime | None
    source_url: str | None


class Valuation(BaseModel):
    ticker: str
    known_at: datetime
    price: PriceOut
    metrics: list[MetricOut]


def universe_equity(session: Session, ticker: str) -> Instrument:
    """The instrument with this open SEC ticker, issued by a known entity; 404 otherwise."""
    instrument = session.scalars(
        select(Instrument)
        .join(Identifier, Identifier.instrument_id == Instrument.id)
        .where(open_sec("ticker"), Identifier.id_value == ticker.upper())
    ).first()
    if instrument is None or instrument.entity_id is None:
        raise HTTPException(status_code=404, detail=f"unknown instrument {ticker!r}")
    return instrument


def filing_forms(session: Session, views: Iterable[FactView]) -> dict[str, str]:
    """Accession -> form, for the filings behind these facts."""
    accessions = {v.row.accession_id for v in views if v.row.accession_id}
    return dict(
        session.execute(
            select(Filing.accession_number, Filing.form)
            .where(Filing.accession_number.in_(accessions))
            .ext(distinct_on(Filing.accession_number))
            .order_by(Filing.accession_number)
        ).all()
    )


def source_out(view: FactView, forms: dict[str, str]) -> SourceOut:
    fact = view.row
    return SourceOut(
        metric_id=fact.metric_id,
        source_concept=fact.source_concept,
        value=fact.value,
        period_start=fact.period_start,
        period_end=fact.period_end,
        filing=FilingRef(
            accession=fact.accession_id or "",
            form=forms.get(fact.accession_id or ""),
            url=fact.source_url,
            published_at=fact.published_at,
            published_at_precision=fact.published_at_precision,
        ),
    )


def input_out(value: Input[FactView], forms: dict[str, str]) -> InputOut:
    return InputOut(
        name=value.name,
        value=value.value,
        period_start=value.period_start,
        period_end=value.period_end,
        note=value.note,
        sources=[source_out(f, forms) for f in value.sources],
    )


def price_out(price: PriceInput, urls: dict[date, str]) -> PriceOut:
    close = price.close
    return PriceOut(
        status=price.status,
        detail=price.detail,
        day=close.day if close else None,
        close=close.close if close else None,
        feed_status=close.feed_status if close else None,
        published_at=close.published_at if close else None,
        source_url=urls.get(close.day) if close else None,
    )


@router.get("/instruments/{ticker}/valuation")
def instrument_valuation(
    ticker: str,
    session: SessionDep,
    known_at: Annotated[
        AwareDatetime | None, Query(description="Point in time (ADR-012); default now")
    ] = None,
) -> Valuation:
    instrument = universe_equity(session, ticker)
    assert instrument.entity_id is not None
    at: datetime = known_at or session.execute(select(func.now())).scalar_one()
    chain = issuer_chain(session, instrument.entity_id)
    rows = session.scalars(
        as_of_query(FinancialFact, known_at=at).where(
            FinancialFact.entity_id.in_(chain.order),
            FinancialFact.metric_id.in_(VALUATION_METRICS),
        )
    ).all()
    facts = [FactView(f) for f in merge_by_precedence(rows, chain.order)]
    splits = [
        Split(s.ex_date, s.old_rate, s.new_rate)
        for s in session.scalars(
            select(SplitEvent).where(
                SplitEvent.instrument_id == instrument.id, SplitEvent.published_at <= at
            )
        )
    ]
    bars = daily_bars(
        session, instrument.id, "raw", since=at - PRICE_LOOKBACK, until=at, known_at=at
    )
    price = select_price(
        [Close(b.bar_date, b.close, b.feed_status, b.published_at) for b in bars], at
    )
    results = valuation(facts, price, splits)
    forms = filing_forms(session, (f for v in results for i in v.inputs for f in i.sources))
    return Valuation(
        ticker=ticker.upper(),
        known_at=at,
        price=price_out(price, {bar.bar_date: bar.source_url for bar in bars}),
        metrics=[
            MetricOut(
                metric_id=v.metric_id,
                unit=v.unit,
                value=v.value,
                reason=v.reason,
                detail=v.detail,
                inputs=[input_out(i, forms) for i in v.inputs],
            )
            for v in results
        ],
    )
