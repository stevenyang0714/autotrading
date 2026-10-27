"""Price, trend and factors (M2.2, ADR-030): the stored factor snapshots as known at T, each
measure with its inputs and its percentile in the instrument's own history. Nothing is computed
on request.

- `GET /instruments/{ticker}/factors`: one universe instrument (equity or ETF) of either
  market (a Taiwan code since M3.7, ADR-039 TW10, under its market's definition set and
  benchmark, on its market's months): the price measures of its latest snapshot at or before
  T, the value and quality measures of its latest full snapshot, each with its percentile among
  the last snapshot of every month since the set's history start, and that monthly history.
- `GET /factors`: every US universe instrument's latest values (the Opportunity Radar table).
- `GET /factors/definitions`: the released definition sets.
Time-series only (P2-3): a percentile compares an instrument with its own past, never with the
other instruments (KI-1).
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from autotrading.api.data_health import SessionDep
from autotrading.api.research import KnownAt
from autotrading.api.valuation import known_at_or_now
from autotrading.db.models import FactorDefinitionSet as FactorDefinitionSetRow
from autotrading.db.models import FactorSnapshot
from autotrading.domain.factors import FactorSnapshot as Snapshot
from autotrading.domain.factors import Measure
from autotrading.domain.fair_value import relative
from autotrading.domain.markets import MARKETS, Market, market_of_code
from autotrading.domain.provenance import end_of_day
from autotrading.repositories.factors import (
    Target,
    active_factor_version,
    load_factor_definitions,
    stored_definitions,
    targets,
)

router = APIRouter(tags=["factors"])

TIME_SERIES_ONLY = (
    "Each value is compared with the instrument's own history since 2016, never ranked against "
    "the other instruments: the universe has no delisted companies (P2-3, KI-1). Descriptions of "
    "the past, not forecasts or signals."
)


class MeasureOut(Measure):
    percentile: Decimal | None  # share of the monthly history at or below the value, percent
    median: Decimal | None
    observations: int
    since: date | None


class SnapshotRef(BaseModel):
    known_at: datetime
    system_time: datetime
    backfilled: bool
    scope: Literal["price", "all"]
    last_close: date | None
    feed_status: str | None


class HistoryPoint(BaseModel):
    known_at: datetime
    values: dict[str, str | None]


class InstrumentFactorsOut(BaseModel):
    ticker: str
    instrument_type: Literal["equity", "etf"]
    known_at: datetime
    definition_version: str
    market: Market  # US, or TW for a Taiwan code (M3.7)
    benchmark: str  # SPY, or 0050 for Taiwan
    percentile_min_observations: int | None  # fewer month ends: no percentile
    price: SnapshotRef | None  # the snapshot of the price measures
    fundamentals: SnapshotRef | None  # the snapshot of the value and quality measures
    measures: list[MeasureOut]
    history: list[HistoryPoint]  # the last snapshot of each month, oldest first
    detail: str = TIME_SERIES_ONLY


class FactorValue(BaseModel):
    measure_id: str
    group: str
    unit: str
    value: Decimal | None
    reason: str | None
    percentile: Decimal | None
    notes: int  # how many notes the measure carries (see the instrument page)


class FactorRow(BaseModel):
    ticker: str
    instrument_type: Literal["equity", "etf"]
    price: SnapshotRef | None
    fundamentals: SnapshotRef | None
    values: list[FactorValue]


class FactorsOut(BaseModel):
    known_at: datetime
    definition_version: str
    benchmark: str
    rows: list[FactorRow]
    detail: str = TIME_SERIES_ONLY


class FactorDefinitionSetOut(BaseModel):
    definition_version: str
    market: Market
    status: Literal["active", "retired"]
    released: date
    content: dict[str, Any]
    content_sha256: str


def _ref(row: FactorSnapshot) -> SnapshotRef:
    return SnapshotRef(
        known_at=row.known_at,
        system_time=row.system_time,
        backfilled=row.backfilled,
        scope="all" if row.scope == "all" else "price",
        last_close=row.last_close,
        feed_status=row.feed_status,
    )


def _latest(
    session: Session, target: Target, version: str, at: datetime, full: bool
) -> FactorSnapshot | None:
    query = select(FactorSnapshot).where(
        FactorSnapshot.instrument_id == target.instrument.id,
        FactorSnapshot.definition_version == version,
        FactorSnapshot.known_at <= at,
    )
    if full:
        query = query.where(FactorSnapshot.scope == "all")
    return session.scalars(query.order_by(FactorSnapshot.known_at.desc()).limit(1)).first()


def _monthly(
    session: Session,
    instrument_ids: list[Any],
    version: str,
    at: datetime,
    since: date,
    full: bool,
    market: Market = "US",
) -> dict[Any, list[tuple[datetime, dict[str, Any]]]]:
    """Per instrument, its last snapshot of each month of its market's zone (New York, or Taipei)
    since `since` known by T, oldest first; with `full`, its last full one (value and quality
    measures)."""
    zone = MARKETS[market].zone
    month = func.date_trunc("month", func.timezone(zone.key, FactorSnapshot.known_at))
    query = (
        select(FactorSnapshot.instrument_id, FactorSnapshot.known_at, FactorSnapshot.measure_values)
        .where(
            FactorSnapshot.instrument_id.in_(instrument_ids),
            FactorSnapshot.definition_version == version,
            FactorSnapshot.known_at <= at,
            FactorSnapshot.known_at >= end_of_day(since, zone.key) - timedelta(days=1),
        )
        .ext(distinct_on(FactorSnapshot.instrument_id, month))
        .order_by(FactorSnapshot.instrument_id, month, FactorSnapshot.known_at.desc())
    )
    if full:
        query = query.where(FactorSnapshot.scope == "all")
    out: dict[Any, list[tuple[datetime, dict[str, Any]]]] = defaultdict(list)
    for instrument_id, known_at, values in session.execute(query):
        if known_at.astimezone(zone).date() >= since:
            out[instrument_id].append((known_at, values))
    return out


def _points(
    history: list[tuple[datetime, dict[str, Any]]], measure_id: str, market: Market = "US"
) -> list[tuple[date, Decimal]]:
    zone = MARKETS[market].zone
    return [
        (known_at.astimezone(zone).date(), Decimal(str(values[measure_id])))
        for known_at, values in history
        if values.get(measure_id) is not None
    ]


def _attributed(measures: list[Measure], benchmark: str) -> list[Measure]:
    """A relative measure stores its own notes and the benchmark's together; name the
    benchmark's (those not on the instrument's own measure) so they are not read as the
    instrument's."""
    own = {m.measure_id: set(m.notes) for m in measures}
    out = []
    for m in measures:
        base = own.get(m.measure_id.removeprefix("relative_"), set())
        if m.group == "relative" and m.notes:
            notes = [n if n in base else f"{benchmark}: {n}" for n in m.notes]
            m = m.model_copy(update={"notes": notes})
        out.append(m)
    return out


def _measures(
    price: FactorSnapshot | None,
    full: FactorSnapshot | None,
    history: list[tuple[datetime, dict[str, Any]]],
    full_history: list[tuple[datetime, dict[str, Any]]],
    benchmark: str = "SPY",
    market: Market = "US",
    min_observations: int | None = None,
) -> list[MeasureOut]:
    """The price measures of `price` and the value and quality measures of `full`, each with its
    percentile in the monthly history (the full snapshots' for value and quality); none below
    `min_observations` month ends (ADR-039 TW10)."""
    chosen: list[Measure] = []
    if price is not None:
        chosen += [
            m
            for m in _attributed(Snapshot.model_validate(price.snapshot).measures, benchmark)
            if m.group in ("trend", "risk", "relative")
        ]
    if full is not None:
        chosen += [
            m
            for m in Snapshot.model_validate(full.snapshot).measures
            if m.group in ("value", "quality")
        ]
    out = []
    for measure in chosen:
        months = full_history if measure.group in ("value", "quality") else history
        found = relative(
            measure.measure_id, measure.value, _points(months, measure.measure_id, market)
        )
        enough = min_observations is None or found.observations >= min_observations
        out.append(
            MeasureOut(
                **measure.model_dump(),
                percentile=found.percentile if enough else None,
                median=found.median if enough else None,
                observations=found.observations,
                since=found.since,
            )
        )
    return out


def _settings(session: Session, version: str) -> tuple[date, str, int | None]:
    """The definition set's percentile history start, benchmark and fewest month ends."""
    definitions = stored_definitions(session, version)
    if definitions is None:
        return date(2016, 1, 1), "SPY", None
    return (
        definitions.percentile_since,
        definitions.benchmark,
        definitions.percentile_min_observations,
    )


@router.get("/factors/definitions")
def factor_definitions(session: SessionDep) -> list[FactorDefinitionSetOut]:
    file = load_factor_definitions()
    status = {d.definition_version: d.status for d in file.definition_sets}
    return [
        FactorDefinitionSetOut(
            definition_version=row.definition_version,
            market=row.content.get("market", "US"),
            status=status.get(row.definition_version, "retired"),
            released=row.released,
            content=row.content,
            content_sha256=row.content_sha256,
        )
        for row in session.scalars(
            select(FactorDefinitionSetRow).order_by(
                FactorDefinitionSetRow.loaded_at.desc(),
                FactorDefinitionSetRow.definition_version.desc(),
            )
        )
    ]


@router.get("/instruments/{ticker}/factors")
def instrument_factors(
    ticker: str, session: SessionDep, known_at: KnownAt = None
) -> InstrumentFactorsOut:
    code = ticker.upper()
    market = market_of_code(code)
    found = targets(session, [code], market)
    if not found:
        raise HTTPException(status_code=404, detail=f"{code} is not in the universe")
    target = found[0]
    at = known_at_or_now(session, known_at)
    version = active_factor_version(market)
    price = _latest(session, target, version, at, full=False)
    full = _latest(session, target, version, at, full=True)
    since, benchmark, minimum = _settings(session, version)
    ids = [target.instrument.id]
    history = _monthly(session, ids, version, at, since, False, market).get(ids[0], [])
    full_history = _monthly(session, ids, version, at, since, True, market).get(ids[0], [])
    fundamentals = full if target.kind == "equity" and market == "US" else None
    return InstrumentFactorsOut(
        ticker=target.symbol,
        instrument_type=target.kind,
        known_at=at,
        definition_version=version,
        market=market,
        benchmark=benchmark,
        percentile_min_observations=minimum,
        price=_ref(price) if price else None,
        fundamentals=_ref(fundamentals) if fundamentals else None,
        measures=_measures(price, fundamentals, history, full_history, benchmark, market, minimum),
        history=[HistoryPoint(known_at=k, values=v) for k, v in history],
    )


@router.get("/factors")
def factors_table(session: SessionDep, known_at: KnownAt = None) -> FactorsOut:
    at = known_at_or_now(session, known_at)
    version = active_factor_version()
    everything = targets(session)
    ids = [t.instrument.id for t in everything]
    since, benchmark, _ = _settings(session, version)
    histories = _monthly(session, ids, version, at, since, full=False)
    full_histories = _monthly(session, ids, version, at, since, full=True)
    rows = []
    for target in everything:
        price = _latest(session, target, version, at, full=False)
        full = _latest(session, target, version, at, full=True) if target.kind == "equity" else None
        measures = _measures(
            price,
            full,
            histories.get(target.instrument.id, []),
            full_histories.get(target.instrument.id, []),
            benchmark,
        )
        rows.append(
            FactorRow(
                ticker=target.symbol,
                instrument_type=target.kind,
                price=_ref(price) if price else None,
                fundamentals=_ref(full) if full else None,
                values=[
                    FactorValue(
                        measure_id=m.measure_id,
                        group=m.group,
                        unit=m.unit,
                        value=m.value,
                        reason=m.reason,
                        percentile=m.percentile,
                        notes=len(m.notes),
                    )
                    for m in measures
                ],
            )
        )
    return FactorsOut(
        known_at=at,
        definition_version=version,
        benchmark=benchmark,
        rows=rows,
    )
