"""Research API (M1.3b, ADR-024): a universe equity's Research Record and the Fundamental
Research dashboard, as known at a time. Read-only.

- GET /instruments/{ticker}/research: economics, quality and capital allocation for the last
  four quarters and the last five fiscal years, each value with its inputs and the filings
  behind them (domain/research.py).
- GET /research: one row per universe equity (R1): the latest period's values, the M1.2
  multiples, and the DCF with the latest assumption version saved by then (R4: no month-end
  history, which stays on the instrument page). The DCF columns are model output, not fact.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import AwareDatetime, BaseModel

from autotrading.api.data_health import SessionDep
from autotrading.api.fair_value import (
    FAIR_VALUE_METRICS,
    MODEL_OUTPUT,
    chosen_version,
    dcf_snapshot,
    risk_free_at,
)
from autotrading.api.instruments import FactView, issuer_chain, universe_equities
from autotrading.api.valuation import (
    MetricOut,
    PriceOut,
    filing_forms,
    known_at_or_now,
    market_view,
    metric_out,
    universe_equity,
)
from autotrading.domain.research import RESEARCH_METRICS, Section, Window, research_record
from autotrading.domain.valuation import Unit, Valued, valuation

router = APIRouter(tags=["research"])

LOADED_METRICS = tuple(dict.fromkeys((*RESEARCH_METRICS, *FAIR_VALUE_METRICS)))
DASHBOARD_MULTIPLES = ("pe_ratio_ttm", "ev_to_ebitda", "fcf_yield")
KnownAt = Annotated[AwareDatetime | None, Query(description="Point in time (ADR-012); default now")]


class ResearchPeriod(BaseModel):
    kind: Literal["ttm", "fiscal_year"]
    period_start: date
    period_end: date


class ResearchRow(BaseModel):
    metric_id: str
    section: Section
    unit: Unit
    cells: list[MetricOut]  # one per period, in the order of `periods`


class ResearchRecordOut(BaseModel):
    ticker: str
    known_at: datetime
    periods: list[ResearchPeriod]  # newest first: TTM (when later than the last year), years
    rows: list[ResearchRow]


class ResearchValue(BaseModel):
    metric_id: str
    unit: Unit
    value: Decimal | None
    reason: Literal["unavailable", "not_meaningful"] | None
    detail: str | None


class ResearchFairValue(BaseModel):
    status: Literal["ok", "unavailable", "not_meaningful"]
    detail: str | None
    assumptions_version: int | None  # None: the built-in default
    base_per_share: Decimal | None
    implied_upside: Decimal | None  # percent
    reverse_dcf_growth: Decimal | None  # percent a year, years 1-5
    comparison_detail: str | None  # why the upside is unavailable


class ResearchSummaryRow(BaseModel):
    ticker: str
    name: str
    period: ResearchPeriod | None  # the latest period the values are for
    price: PriceOut
    values: list[ResearchValue]  # the latest period's record values, then the multiples
    fair_value: ResearchFairValue


class ResearchDashboard(BaseModel):
    known_at: datetime
    label: Literal["Model output, not fact"]  # for the DCF columns
    rows: list[ResearchSummaryRow]


def _period(window: Window) -> ResearchPeriod:
    return ResearchPeriod(kind=window.kind, period_start=window.start, period_end=window.end)


def _value(value: Valued[FactView]) -> ResearchValue:
    return ResearchValue(
        metric_id=value.metric_id,
        unit=value.unit,
        value=value.value,
        reason=value.reason,
        detail=value.detail,
    )


@router.get("/instruments/{ticker}/research")
def instrument_research(
    ticker: str, session: SessionDep, known_at: KnownAt = None
) -> ResearchRecordOut:
    instrument = universe_equity(session, ticker)
    assert instrument.entity_id is not None
    at = known_at_or_now(session, known_at)
    chain = issuer_chain(session, instrument.entity_id)
    view = market_view(session, instrument, chain.order, at, RESEARCH_METRICS)
    record = research_record(view.facts, at, view.splits)
    forms = filing_forms(
        session,
        (f for *_, values in record.rows for v in values for i in v.inputs for f in i.sources),
    )
    return ResearchRecordOut(
        ticker=ticker.upper(),
        known_at=at,
        periods=[_period(w) for w in record.periods],
        rows=[
            ResearchRow(
                metric_id=metric,
                section=section,
                unit=unit,
                cells=[metric_out(v, forms) for v in values],
            )
            for section, metric, unit, values in record.rows
        ],
    )


@router.get("/research")
def research_dashboard(session: SessionDep, known_at: KnownAt = None) -> ResearchDashboard:
    at = known_at_or_now(session, known_at)
    risk_free = risk_free_at(session, at)
    rows = []
    for ticker, instrument, entity in universe_equities(session):
        chain = issuer_chain(session, entity.id)
        view = market_view(session, instrument, chain.order, at, LOADED_METRICS)
        record = research_record(view.facts, at, view.splits)
        latest = [values[0] for *_, values in record.rows] if record.periods else []
        multiples = [
            v
            for v in valuation(view.facts, view.price, view.splits)
            if v.metric_id in DASHBOARD_MULTIPLES
        ]
        chosen = chosen_version(session, instrument.id, None, at)
        snapshot = dcf_snapshot(view, chosen.parameters, risk_free, at)
        result = snapshot.result
        base = result.scenarios.get("base")
        rows.append(
            ResearchSummaryRow(
                ticker=ticker,
                name=entity.name,
                period=_period(record.periods[0]) if record.periods else None,
                price=view.price_out(),
                values=[_value(v) for v in (*latest, *multiples)],
                fair_value=ResearchFairValue(
                    status=result.status,
                    detail=result.detail,
                    assumptions_version=chosen.version,
                    base_per_share=base.per_share if base else None,
                    implied_upside=result.implied_upside,
                    reverse_dcf_growth=result.reverse_growth,
                    comparison_detail=snapshot.comparison_detail,
                ),
            )
        )
    return ResearchDashboard(known_at=at, label=MODEL_OUTPUT, rows=rows)
