"""Factor snapshots (M2.2, ADR-030): each universe instrument's price, trend and factor measures
at (T, S), stored in the caller's transaction.

Every input is read as known at T and as this database held it at S (closes through
`daily_bars`, splits and dividends by publication and recorded_at, facts through `market_view`),
so a stored snapshot recomputes identically. One snapshot per instrument, T and definition
version; re-running is harmless. Percentiles against the instrument's own history are read
from the stored snapshots, never stored.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Literal, cast
from uuid import UUID

import yaml
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from autotrading.adapters.alpaca.refresh import universe
from autotrading.api.instruments import FactView, issuer_chain
from autotrading.api.valuation import VALUATION_METRICS, market_view, recorded_by
from autotrading.db.models import DividendEvent, FactorSnapshot, Instrument, SplitEvent
from autotrading.db.models import FactorDefinitionSet as FactorDefinitionSetRow
from autotrading.domain.factors import (
    Dividend,
    FactorDefinitionSet,
    FactorDefinitionsFile,
    FactorInput,
    Measure,
    MeasureUnit,
    Series,
    price_measures,
)
from autotrading.domain.factors import FactorSnapshot as Snapshot
from autotrading.domain.fair_value import month_ends
from autotrading.domain.provenance import end_of_day
from autotrading.domain.research import RESEARCH_METRICS, ROWS, research_record
from autotrading.domain.splits import Split
from autotrading.domain.valuation import METRICS, Close, Valued, valuation
from autotrading.repositories.audit import set_actor
from autotrading.repositories.prices import daily_bars, instruments_by_symbol
from autotrading.settings import get_settings

ACTOR = "rules:factor_definitions"
BARS = timedelta(days=420)  # 253 sessions for 12-1 momentum and beta, with holidays
# Each value and quality measure's unit, also when the Research Record has no value for it.
UNITS: dict[str, MeasureUnit] = {
    metric: cast(MeasureUnit, unit)
    for metric, unit in (*METRICS, *((m, u) for _, m, u in ROWS))
    if unit in ("percent", "x")
}


def load_factor_definitions(path: Path | None = None) -> FactorDefinitionsFile:
    path = path or get_settings().resolved_config_dir() / "factor_definitions.yaml"
    return FactorDefinitionsFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache
def _file() -> FactorDefinitionsFile:
    return load_factor_definitions()


def active_factor_version() -> str:
    return _file().active().definition_version


def stored_definitions(
    session: Session, definition_version: str | None = None
) -> FactorDefinitionSet | None:
    """A released definition set as `make migrate` registered it; None when not loaded."""
    version = definition_version or active_factor_version()
    row = session.scalars(
        select(FactorDefinitionSetRow).where(FactorDefinitionSetRow.definition_version == version)
    ).first()
    return FactorDefinitionSet.model_validate(row.content) if row else None


@dataclass(frozen=True)
class Target:
    """One universe instrument: its Alpaca symbol, kind and (for an equity) its issuer."""

    symbol: str
    instrument: Instrument

    @property
    def kind(self) -> Literal["equity", "etf"]:
        return "etf" if self.instrument.instrument_type == "etf" else "equity"


def targets(session: Session, symbols: Iterable[str] | None = None) -> list[Target]:
    """The universe instruments (config/universe.yaml order) that have an instrument row."""
    everything, _ = universe(get_settings().resolved_config_dir())
    wanted = [s for s in everything if symbols is None or s in set(symbols)]
    ids = instruments_by_symbol(session, wanted)
    rows = {
        i.id: i for i in session.scalars(select(Instrument).where(Instrument.id.in_(ids.values())))
    }
    return [Target(s, rows[ids[s]]) for s in wanted if s in ids]


def series_at(
    session: Session, symbol: str, instrument_id: UUID, at: datetime, system_time: datetime
) -> Series:
    """One instrument's closes, splits and dividends known at (T, S)."""
    bars = daily_bars(
        session,
        instrument_id,
        "raw",
        since=at - BARS,
        until=at,
        known_at=at,
        system_time=system_time,
    )
    splits = [
        Split(s.ex_date, s.old_rate, s.new_rate)
        for s in session.scalars(
            select(SplitEvent).where(
                SplitEvent.instrument_id == instrument_id,
                SplitEvent.published_at <= at,
                recorded_by(SplitEvent.recorded_at, system_time),
            )
        )
    ]
    dividends = [
        Dividend(d.ex_date, d.rate, d.special)
        for d in session.scalars(
            select(DividendEvent).where(
                DividendEvent.instrument_id == instrument_id,
                DividendEvent.published_at <= at,
                recorded_by(DividendEvent.recorded_at, system_time),
            )
        )
    ]
    return Series(
        symbol,
        [Close(b.bar_date, b.close, b.feed_status, b.published_at) for b in bars],
        splits,
        dividends,
    )


def _inputs(value: Valued[FactView]) -> list[FactorInput]:
    return [
        FactorInput(
            name=i.name,
            value=i.value,
            start=i.period_start,
            end=i.period_end,
            note=i.note,
            sources=sorted({f.row.accession_id for f in i.sources if f.row.accession_id}),
        )
        for i in value.inputs
    ]


def _fundamental(
    value: Valued[FactView] | None,
    metric_id: str,
    group: Literal["value", "quality"],
    detail: str,
    start: date | None,
    end: date | None,
) -> Measure:
    if value is None:
        return Measure(
            measure_id=metric_id,
            group=group,
            unit=UNITS[metric_id],
            value=None,
            reason="unavailable",
            detail="not in the Research Record at this time",
        )
    return Measure(
        measure_id=metric_id,
        group=group,
        unit=UNITS[metric_id],
        value=value.value,
        reason=value.reason,
        detail=value.detail or detail,
        start=start,
        end=end,
        inputs=_inputs(value),
    )


def fundamental_measures(
    session: Session,
    definitions: FactorDefinitionSet,
    instrument: Instrument,
    at: datetime,
    system_time: datetime,
) -> list[Measure]:
    """The value and quality measures of an equity at (T, S): the latest period of its Research
    Record and the multiples on the last close known then."""
    assert instrument.entity_id is not None
    chain = issuer_chain(session, instrument.entity_id)
    metrics = tuple(dict.fromkeys((*RESEARCH_METRICS, *VALUATION_METRICS)))
    view = market_view(session, instrument, chain.order, at, metrics, system_time=system_time)
    record = research_record(view.facts, at, view.splits)
    latest = {metric: values[0] for _, metric, _, values in record.rows} if record.periods else {}
    period = record.periods[0] if record.periods else None
    multiples = {v.metric_id: v for v in valuation(view.facts, view.price, view.splits)}
    price_day = view.price.close.day if view.price.close else None
    out = [
        _fundamental(
            multiples.get(metric),
            metric,
            "value",
            f"on the close of {price_day}" if price_day else view.price.detail,
            None,
            price_day,
        )
        for metric in definitions.fundamentals.value
    ]
    out += [
        _fundamental(
            latest.get(metric),
            metric,
            "quality",
            f"{period.kind} {period.start} to {period.end}" if period else "no period",
            period.start if period else None,
            period.end if period else None,
        )
        for metric in definitions.fundamentals.quality
    ]
    return out


def snapshot_at(
    session: Session,
    definitions: FactorDefinitionSet,
    target: Target,
    at: datetime,
    system_time: datetime,
    scope: Literal["price", "all"],
    benchmark: Series | None = None,
) -> Snapshot:
    """One instrument's snapshot at (T, S). `benchmark`: the benchmark's evidence at (T, S),
    read here when not given."""
    series = series_at(session, target.symbol, target.instrument.id, at, system_time)
    if benchmark is None and target.symbol != definitions.benchmark:
        found = targets(session, [definitions.benchmark])
        if found:
            benchmark = series_at(
                session, definitions.benchmark, found[0].instrument.id, at, system_time
            )
    measures, last = price_measures(definitions, at, series, benchmark)
    if scope == "all" and target.kind == "equity" and target.instrument.entity_id is not None:
        measures += fundamental_measures(session, definitions, target.instrument, at, system_time)
    return Snapshot(
        definition_version=definitions.definition_version,
        known_at=at,
        symbol=target.symbol,
        instrument_type=target.kind,
        scope=scope,
        last_close=last.day if last else None,
        feed_status=last.feed_status if last else None,
        measures=measures,
    )


def record_snapshot(
    session: Session,
    definitions: FactorDefinitionSet,
    target: Target,
    at: datetime,
    system_time: datetime,
    scope: Literal["price", "all"],
    trigger: str,
    benchmark: Series | None = None,
) -> bool:
    """Store one instrument's snapshot at T; False when it is stored already."""
    set_actor(session, ACTOR)
    snapshot = snapshot_at(session, definitions, target, at, system_time, scope, benchmark)
    inserted = session.execute(
        insert(FactorSnapshot)
        .values(
            instrument_id=target.instrument.id,
            symbol=target.symbol,
            known_at=at,
            system_time=system_time,
            definition_version=definitions.definition_version,
            scope=scope,
            last_close=snapshot.last_close,
            feed_status=snapshot.feed_status,
            measure_values=snapshot.values(),
            snapshot=snapshot.model_dump(mode="json"),
            backfilled=system_time > at,
            trigger=trigger,
        )
        .on_conflict_do_nothing(constraint="uq_factor_snapshots_key")
        .returning(FactorSnapshot.id)
    ).scalar()
    return inserted is not None


def record_universe(
    session: Session,
    definitions: FactorDefinitionSet,
    points: Sequence[tuple[datetime, Literal["price", "all"]]],
    system_time: datetime,
    trigger: str,
    symbols: Iterable[str] | None = None,
) -> int:
    """Snapshots of the universe (or `symbols`) at each (T, scope), committing after each T;
    the benchmark's evidence is read once per T. Returns how many were stored."""
    chosen = targets(session, symbols)
    bench = targets(session, [definitions.benchmark])
    stored = 0
    for at, scope in points:
        benchmark = (
            series_at(session, definitions.benchmark, bench[0].instrument.id, at, system_time)
            if bench
            else None
        )
        for target in chosen:
            stored += record_snapshot(
                session, definitions, target, at, system_time, scope, trigger, benchmark
            )
        session.commit()
    return stored


def backfill_points(
    session: Session, definitions: FactorDefinitionSet, year: int, system_time: datetime
) -> list[tuple[datetime, Literal["price", "all"]]]:
    """The points of one year to backfill (ADR-030 F2): the end of every session the benchmark
    has a close for (price measures) and every month end (all measures), up to `system_time`."""
    bench = targets(session, [definitions.benchmark])
    if not bench:
        return []
    start = datetime(year, 1, 1, tzinfo=UTC)
    end = min(system_time, datetime(year + 1, 1, 1, tzinfo=UTC))
    bars = daily_bars(
        session,
        bench[0].instrument.id,
        "raw",
        since=start - timedelta(days=1),
        until=end + timedelta(days=1),
        known_at=system_time,
        system_time=system_time,
    )
    sessions = {end_of_day(b.bar_date) for b in bars if b.bar_date.year == year}
    months = {p for p in month_ends(date(year, 1, 1), end) if p.year == year or p < end}
    points = sorted(p for p in sessions | months if p <= system_time)
    return [(p, "all" if p in months else "price") for p in points]


def recompute(session: Session, row: FactorSnapshot) -> Snapshot | None:
    """A stored snapshot recomputed with its own T, S, scope and definition version."""
    definitions = stored_definitions(session, row.definition_version)
    found = targets(session, [row.symbol])
    if definitions is None or not found:
        return None
    scope = cast(Literal["price", "all"], row.scope)
    return snapshot_at(session, definitions, found[0], row.known_at, row.system_time, scope)


def same(row: FactorSnapshot, again: Snapshot | None) -> bool:
    return again is not None and Snapshot.model_validate(row.snapshot) == again
