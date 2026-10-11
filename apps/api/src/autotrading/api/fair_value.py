"""Fair value API (M1.3a, ADR-023): DCF scenarios, reverse DCF and relative valuation of a
universe equity as known at a time, with the assumption version they used. Model output, not
fact (02 §32.2).

- GET  /instruments/{ticker}/fair-value: the models at `known_at` with one assumption version
  (default: the latest saved by then, else the built-in default).
- GET  /instruments/{ticker}/assumptions: the built-in default and every saved version.
- POST /instruments/{ticker}/assumptions: save a new version. The first endpoint that writes:
  append-only (a new version each time, never an edit), audited as actor `web`. The API port
  is bound to 127.0.0.1 (docker-compose.yml), so only this machine can call it.

Reproducible: the output depends only on what was public at `known_at` (facts, closes,
splits, the 10-year Treasury yield) and the assumption version, so the same pair always gives
the same numbers.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Annotated, Literal

from annotated_types import Ge, Le
from fastapi import APIRouter, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from autotrading.api.data_health import SessionDep
from autotrading.api.instruments import FactView, FilingRef, issuer_chain
from autotrading.api.valuation import (
    PRICE_LOOKBACK,
    VALUATION_METRICS,
    InputOut,
    MarketView,
    PriceOut,
    filing_forms,
    input_out,
    known_at_or_now,
    market_view,
    source_out,
    universe_equity,
)
from autotrading.db.models import FinancialFact, MacroObservation, ValuationAssumptionSet
from autotrading.domain.fair_value import (
    DEFAULT_ASSUMPTIONS,
    HISTORY_SINCE,
    RELATIVE_METRICS,
    SCENARIOS,
    Assumptions,
    FairValue,
    RiskFree,
    Scenario,
    fair_value,
    month_ends,
    multiple_history,
    relative,
    snapshots,
)
from autotrading.domain.fundamentals import merge_by_precedence
from autotrading.domain.valuation import (
    METRICS,
    Input,
    Unit,
    close_basis,
    latest_net_debt,
    share_count,
    valuation,
)
from autotrading.repositories.audit import set_actor
from autotrading.repositories.facts import as_of_query, row_key

router = APIRouter(tags=["fair-value"])

FAIR_VALUE_METRICS = (*VALUATION_METRICS, "stock_based_compensation")
RISK_FREE_SERIES = "DGS10"
ACTOR = "web"
MODEL_OUTPUT: Literal["Model output, not fact"] = "Model output, not fact"
METHOD = (
    "Enterprise DCF of owner free cash flow (operating cash flow - capex - stock-based "
    "compensation, last four quarters): five years at the scenario growth, five years fading "
    "linearly to the terminal growth, then a terminal value; annual, discounted at year end "
    "at the 10-year Treasury yield + the equity risk premium; minus net debt, divided by "
    "shares outstanding. Relative: each multiple against its own month-end history since "
    f"{HISTORY_SINCE.year}, each month as known then."
)
DEFAULT_REASON = "Built-in default shared by every company; not reviewed"
UNITS = dict(METRICS)


# ---------- assumptions ----------


class AssumptionVersion(BaseModel):
    version: int | None  # None: the built-in default (ADR-023 F3)
    parameters: Assumptions
    reason: str
    author: str | None
    created_at: datetime | None


class Limit(BaseModel):
    minimum: Decimal
    maximum: Decimal


class AssumptionList(BaseModel):
    ticker: str
    default: AssumptionVersion
    versions: list[AssumptionVersion]  # newest first
    limits: dict[str, Limit]  # percent, inclusive


class NewAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parameters: Assumptions
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


DEFAULT_VERSION = AssumptionVersion(
    version=None,
    parameters=DEFAULT_ASSUMPTIONS,
    reason=DEFAULT_REASON,
    author=None,
    created_at=None,
)


def _limits() -> dict[str, Limit]:
    out: dict[str, Limit] = {}
    for name, info in Assumptions.model_fields.items():
        low = next((m.ge for m in info.metadata if isinstance(m, Ge)), None)
        high = next((m.le for m in info.metadata if isinstance(m, Le)), None)
        if low is not None and high is not None:
            out[name] = Limit(minimum=Decimal(str(low)), maximum=Decimal(str(high)))
    return out


def _version_out(row: ValuationAssumptionSet) -> AssumptionVersion:
    return AssumptionVersion(
        version=row.version,
        parameters=Assumptions.model_validate(row.parameters),
        reason=row.reason,
        author=row.author,
        created_at=row.created_at,
    )


def _saved(session: Session, instrument_id: object) -> list[ValuationAssumptionSet]:
    return list(
        session.scalars(
            select(ValuationAssumptionSet)
            .where(ValuationAssumptionSet.instrument_id == instrument_id)
            .order_by(ValuationAssumptionSet.version.desc())
        )
    )


@router.get("/instruments/{ticker}/assumptions")
def list_assumptions(ticker: str, session: SessionDep) -> AssumptionList:
    instrument = universe_equity(session, ticker)
    return AssumptionList(
        ticker=ticker.upper(),
        default=DEFAULT_VERSION,
        versions=[_version_out(row) for row in _saved(session, instrument.id)],
        limits=_limits(),
    )


@router.post("/instruments/{ticker}/assumptions", status_code=201)
def save_assumptions(ticker: str, body: NewAssumptions, session: SessionDep) -> AssumptionVersion:
    """A new version (the latest + 1); earlier versions are never changed."""
    instrument = universe_equity(session, ticker)
    set_actor(session, ACTOR)
    latest = session.scalar(
        select(func.max(ValuationAssumptionSet.version)).where(
            ValuationAssumptionSet.instrument_id == instrument.id
        )
    )
    row = ValuationAssumptionSet(
        instrument_id=instrument.id,
        version=(latest or 0) + 1,
        parameters=body.parameters.model_dump(mode="json"),
        reason=body.reason,
        author=ACTOR,
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError as exc:  # another version was saved at the same moment
        session.rollback()
        raise HTTPException(
            status_code=409, detail="another version was just saved; reload and try again"
        ) from exc
    session.refresh(row)
    return _version_out(row)


# ---------- fair value ----------


class RiskFreeOut(BaseModel):
    series_id: str
    value: Decimal  # percent
    observation_date: date
    published_at: datetime
    source_url: str


class DiscountRate(BaseModel):
    value: Decimal | None  # percent: risk-free + equity risk premium
    risk_free: RiskFreeOut | None
    equity_risk_premium: Decimal


class ScenarioOut(BaseModel):
    scenario: Scenario
    growth: Decimal  # percent a year, years 1-5
    per_share: Decimal  # USD
    enterprise_value: Decimal
    explicit_value: Decimal  # present value of years 1-10
    terminal_value: Decimal  # present value of the terminal value


class DcfOut(BaseModel):
    status: Literal["ok", "unavailable", "not_meaningful"]
    detail: str | None
    discount_rate: DiscountRate
    terminal_growth: Decimal  # percent
    inputs: list[InputOut]  # owner free cash flow, net debt, shares outstanding
    scenarios: list[ScenarioOut]  # bear, base, bull: the scenario range


class PriceComparison(BaseModel):
    price: PriceOut
    implied_upside: Decimal | None  # percent: base / price - 1
    margin_of_safety: Decimal | None  # percent: (base - price) / base
    detail: str | None  # why they are unavailable


class ReverseDcf(BaseModel):
    growth: Decimal | None  # percent a year, years 1-5, that the price implies
    detail: str | None


class RelativeOut(BaseModel):
    metric_id: str
    unit: Unit
    current: Decimal | None  # as on the Valuation block
    median: Decimal | None
    percentile: Decimal | None  # share of month ends at or below the current value
    observations: int  # month ends with a value
    since: date | None  # the first of them


class DataAsOf(BaseModel):
    latest_filing: FilingRef | None  # the latest filing behind the DCF inputs
    price_day: date | None
    risk_free_date: date | None


class FairValueOut(BaseModel):
    ticker: str
    known_at: datetime  # the model date: everything below was public by then
    label: Literal["Model output, not fact"]
    method: str
    assumptions: AssumptionVersion
    dcf: DcfOut
    comparison: PriceComparison
    reverse_dcf: ReverseDcf
    relative: list[RelativeOut]
    data_as_of: DataAsOf


def chosen_version(
    session: Session,
    instrument_id: object,
    requested: str | None,
    at: datetime,
    system_time: datetime | None = None,
) -> AssumptionVersion:
    """The requested version; by default the latest saved by `at` (and by `system_time`)."""
    if requested == "default":
        return DEFAULT_VERSION
    saved = _saved(session, instrument_id)
    if requested is None:
        by = at if system_time is None else min(at, system_time)
        known = [row for row in saved if row.created_at <= by]
        return _version_out(known[0]) if known else DEFAULT_VERSION
    row = next((r for r in saved if r.version == int(requested)), None)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no assumption version {requested}")
    return _version_out(row)


def risk_free_at(
    session: Session, at: datetime, system_time: datetime | None = None
) -> RiskFreeOut | None:
    """The latest 10-year Treasury yield observation public at `at`, as this database held
    it at `system_time` (default: now)."""
    known = as_of_query(MacroObservation, known_at=at, system_time=system_time).where(
        MacroObservation.series_id == RISK_FREE_SERIES
    )
    shown = aliased(MacroObservation, known.subquery())
    row = session.scalars(select(shown).order_by(shown.observation_date.desc()).limit(1)).first()
    if row is None:
        return None
    return RiskFreeOut(
        series_id=RISK_FREE_SERIES,
        value=row.value,
        observation_date=row.observation_date,
        published_at=row.published_at,
        source_url=row.source_url,
    )


@dataclass(frozen=True)
class DcfSnapshot:
    """The DCF, reverse DCF and price comparison of one equity at T with one version."""

    result: FairValue[FactView]
    inputs: list[Input[FactView]]  # owner free cash flow, net debt, shares outstanding
    comparison_detail: str | None  # why upside and margin of safety are unavailable


def dcf_snapshot(
    view: MarketView, params: Assumptions, risk_free: RiskFreeOut | None, at: datetime
) -> DcfSnapshot:
    price = view.price
    usable = price.status == "ok" and price.close is not None
    basis = close_basis(price.close) if usable and price.close else at
    net_debt = latest_net_debt(view.facts)
    shares = share_count(view.facts, basis, view.splits)
    result = fair_value(
        view.facts,
        params,
        RiskFree(risk_free.value, risk_free.observation_date, risk_free.published_at)
        if risk_free
        else None,
        net_debt,
        shares,
        price.close.close if usable and price.close else None,
    )
    if result.status != "ok":
        detail: str | None = f"no fair value: {result.detail}"
    elif not usable:
        detail = f"no valuation price: {price.detail}"
    elif result.margin_of_safety is None:
        detail = "the base value is not positive"
    else:
        detail = None
    inputs = [i for i in (result.base_fcf, net_debt, shares) if i is not None]
    return DcfSnapshot(result, inputs, detail)


@router.get("/instruments/{ticker}/fair-value")
def instrument_fair_value(
    ticker: str,
    session: SessionDep,
    known_at: Annotated[
        AwareDatetime | None, Query(description="Point in time (ADR-012); default now")
    ] = None,
    assumptions: Annotated[
        str | None,
        Query(
            pattern=r"^(default|[1-9][0-9]*)$",
            description="Assumption version, or 'default'; default: the latest saved by then",
        ),
    ] = None,
) -> FairValueOut:
    instrument = universe_equity(session, ticker)
    assert instrument.entity_id is not None
    at = known_at_or_now(session, known_at)
    chosen = chosen_version(session, instrument.id, assumptions, at)
    params = chosen.parameters
    chain = issuer_chain(session, instrument.entity_id)

    # Facts, closes and splits known at T (as /valuation shows them); closes since 2016 for
    # the relative history.
    since = datetime.combine(HISTORY_SINCE, time(), tzinfo=UTC) - PRICE_LOOKBACK
    view = market_view(session, instrument, chain.order, at, FAIR_VALUE_METRICS, bars_since=since)
    risk_free = risk_free_at(session, at)
    snapshot = dcf_snapshot(view, params, risk_free, at)
    result, price = snapshot.result, view.price
    forms = filing_forms(session, (f for i in snapshot.inputs for f in i.sources))
    growth = {"bear": params.growth_bear, "base": params.growth_base, "bull": params.growth_bull}

    # Relative valuation: the current multiples (as on the Valuation block) against their
    # month-end history, each month from the fact versions public by then.
    current = {v.metric_id: v.value for v in valuation(view.facts, price, view.splits)}
    versions = session.scalars(
        select(FinancialFact).where(
            FinancialFact.entity_id.in_(chain.order),
            FinancialFact.metric_id.in_(VALUATION_METRICS),
            FinancialFact.published_at <= at,
            FinancialFact.superseded_at.is_(None),
        )
    ).all()
    points = (
        (point, [FactView(f) for f in merge_by_precedence(known, chain.order)])
        for point, known in snapshots(
            versions,
            month_ends(HISTORY_SINCE, at),
            row_key,
            lambda f: f.published_at,
            lambda f: f.recorded_at,
        )
    )
    history = multiple_history(points, view.closes, view.dated_splits)

    sources = [f for i in snapshot.inputs for f in i.sources]
    latest = max(sources, key=lambda f: f.reported_at) if sources else None
    return FairValueOut(
        ticker=ticker.upper(),
        known_at=at,
        label=MODEL_OUTPUT,
        method=METHOD,
        assumptions=chosen,
        dcf=DcfOut(
            status=result.status,
            detail=result.detail,
            discount_rate=DiscountRate(
                value=result.discount_rate,
                risk_free=risk_free,
                equity_risk_premium=params.equity_risk_premium,
            ),
            terminal_growth=params.terminal_growth,
            inputs=[input_out(i, forms) for i in snapshot.inputs],
            scenarios=[
                ScenarioOut(
                    scenario=name,
                    growth=growth[name],
                    per_share=result.scenarios[name].per_share,
                    enterprise_value=result.scenarios[name].enterprise_value,
                    explicit_value=result.scenarios[name].explicit_value,
                    terminal_value=result.scenarios[name].terminal_value,
                )
                for name in SCENARIOS
                if name in result.scenarios
            ],
        ),
        comparison=PriceComparison(
            price=view.price_out(),
            implied_upside=result.implied_upside,
            margin_of_safety=result.margin_of_safety,
            detail=snapshot.comparison_detail,
        ),
        reverse_dcf=ReverseDcf(growth=result.reverse_growth, detail=result.reverse_detail),
        relative=[
            RelativeOut(
                metric_id=r.metric_id,
                unit=UNITS[metric],
                current=r.current,
                median=r.median,
                percentile=r.percentile,
                observations=r.observations,
                since=r.since,
            )
            for metric in RELATIVE_METRICS
            for r in (relative(metric, current.get(metric), history[metric]),)
        ],
        data_as_of=DataAsOf(
            latest_filing=source_out(latest, forms).filing if latest else None,
            price_day=price.close.day if price.close else None,
            risk_free_date=risk_free.observation_date if risk_free else None,
        ),
    )
