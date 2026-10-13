"""Price, trend and factors (M2.2, ADR-030): the stored factor snapshots as known at T, each
measure with its inputs and its percentile in the instrument's own history. Nothing is computed
on request.

- `GET /instruments/{ticker}/factors`: one universe instrument (equity or ETF): the price
  measures of its latest snapshot at or before T, the value and quality measures of its latest
  full snapshot, each with its percentile among the last snapshot of every month since 2016,
  and that monthly history.
- `GET /factors`: every universe instrument's latest values (the Opportunity Radar table).
- `GET /factors/definitions`: the released definition sets.
Time-series only (P2-3): a percentile compares an instrument with its own past, never with the
other instruments (KI-1).
"""

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from autotrading.api.data_health import SessionDep
from autotrading.api.research import KnownAt
from autotrading.api.valuation import known_at_or_now
from autotrading.db.models import FactorDefinitionSet as FactorDefinitionSetRow
from autotrading.db.models import FactorSnapshot
from autotrading.domain.factors import FactorSnapshot as Snapshot
from autotrading.domain.factors import Measure
from autotrading.domain.fair_value import relative
from autotrading.domain.splits import NEW_YORK
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
    session: Session, instrument_ids: list[Any], version: str, at: datetime, since: date
) -> dict[Any, list[tuple[datetime, dict[str, Any]]]]:
    """Per instrument, the last full snapshot of each New York month since `since`, by T."""
    rows = session.execute(
        select(FactorSnapshot.instrument_id, FactorSnapshot.known_at, FactorSnapshot.measure_values)
        .where(
            FactorSnapshot.instrument_id.in_(instrument_ids),
            FactorSnapshot.definition_version == version,
            FactorSnapshot.scope == "all",
            FactorSnapshot.known_at <= at,
        )
        .order_by(FactorSnapshot.known_at)
    ).all()
    by_month: dict[Any, dict[tuple[int, int], tuple[datetime, dict[str, Any]]]] = defaultdict(dict)
    for instrument_id, known_at, values in rows:
        day = known_at.astimezone(NEW_YORK).date()
        if day >= since:
            by_month[instrument_id][(day.year, day.month)] = (known_at, values)
    return {k: list(v.values()) for k, v in by_month.items()}


def _points(
    history: list[tuple[datetime, dict[str, Any]]], measure_id: str
) -> list[tuple[date, Decimal]]:
    return [
        (known_at.astimezone(NEW_YORK).date(), Decimal(str(values[measure_id])))
        for known_at, values in history
        if values.get(measure_id) is not None
    ]


def _measures(
    price: FactorSnapshot | None,
    full: FactorSnapshot | None,
    history: list[tuple[datetime, dict[str, Any]]],
) -> list[MeasureOut]:
    """The price measures of `price` and the value and quality measures of `full`, each with its
    percentile in the monthly history."""
    chosen: list[Measure] = []
    if price is not None:
        chosen += [
            m
            for m in Snapshot.model_validate(price.snapshot).measures
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
        found = relative(measure.measure_id, measure.value, _points(history, measure.measure_id))
        out.append(
            MeasureOut(
                **measure.model_dump(),
                percentile=found.percentile,
                median=found.median,
                observations=found.observations,
                since=found.since,
            )
        )
    return out


def _since(session: Session, version: str) -> date:
    definitions = stored_definitions(session, version)
    return definitions.percentile_since if definitions else date(2016, 1, 1)


@router.get("/factors/definitions")
def factor_definitions(session: SessionDep) -> list[FactorDefinitionSetOut]:
    file = load_factor_definitions()
    status = {d.definition_version: d.status for d in file.definition_sets}
    return [
        FactorDefinitionSetOut(
            definition_version=row.definition_version,
            status=status.get(row.definition_version, "retired"),
            released=row.released,
            content=row.content,
            content_sha256=row.content_sha256,
        )
        for row in session.scalars(
            select(FactorDefinitionSetRow).order_by(FactorDefinitionSetRow.loaded_at.desc())
        )
    ]


@router.get("/instruments/{ticker}/factors")
def instrument_factors(
    ticker: str, session: SessionDep, known_at: KnownAt = None
) -> InstrumentFactorsOut:
    found = targets(session, [ticker.upper()])
    if not found:
        raise HTTPException(status_code=404, detail=f"{ticker.upper()} is not in the universe")
    target = found[0]
    at = known_at_or_now(session, known_at)
    version = active_factor_version()
    price = _latest(session, target, version, at, full=False)
    full = _latest(session, target, version, at, full=True)
    history = _monthly(session, [target.instrument.id], version, at, _since(session, version)).get(
        target.instrument.id, []
    )
    return InstrumentFactorsOut(
        ticker=target.symbol,
        instrument_type=target.kind,
        known_at=at,
        definition_version=version,
        price=_ref(price) if price else None,
        fundamentals=_ref(full) if full and target.kind == "equity" else None,
        measures=_measures(price, full if target.kind == "equity" else None, history),
        history=[HistoryPoint(known_at=k, values=v) for k, v in history],
    )


@router.get("/factors")
def factors_table(session: SessionDep, known_at: KnownAt = None) -> FactorsOut:
    at = known_at_or_now(session, known_at)
    version = active_factor_version()
    everything = targets(session)
    histories = _monthly(
        session, [t.instrument.id for t in everything], version, at, _since(session, version)
    )
    definitions = stored_definitions(session, version)
    rows = []
    for target in everything:
        price = _latest(session, target, version, at, full=False)
        full = _latest(session, target, version, at, full=True) if target.kind == "equity" else None
        measures = _measures(price, full, histories.get(target.instrument.id, []))
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
        benchmark=definitions.benchmark if definitions else "SPY",
        rows=rows,
    )
