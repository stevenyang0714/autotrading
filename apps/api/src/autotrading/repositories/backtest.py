"""Backtests (M2.5, ADR-033): each strategy's targets as they were known at every T, and the
closes, splits and dividends known at the run's end, all as the database held them at the run's
system time S; the stored runs.

- S1: at each month end, the latest buyback state assignment of each company known then (at
  most `state_stale_after_days` old) under the pinned buyback rules; the S1 states hold.
- S3: every rotation target set (month starts and defensive switches) under the pinned
  rotation rules.
- S4: at each month end, the momentum rules on the factor snapshots known then (backtest rules
  0.1.0); since 0.2.0 every target set by the stored daily S4 assessments (ADR-036 D7).

Rows count when known at T and recorded by S, never by T: a backfilled row was computed later
from inputs known at T. `record_run` stores one run per strategy, T and rule versions;
re-running is harmless. Performance is withheld (OD-7).
"""

from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.orm import Session

from autotrading.api.valuation import recorded_by
from autotrading.db.models import BacktestRuleSet as BacktestRuleSetRow
from autotrading.db.models import (
    BacktestRun,
    BuybackStateAssignment,
    DividendEvent,
    FactorSnapshot,
    MomentumAssessment,
    RotationAssessment,
    SplitEvent,
)
from autotrading.db.models import MomentumRuleSet as MomentumRuleSetRow
from autotrading.domain.backtest import (
    BacktestRuleSet,
    BacktestRulesFile,
    Event,
    Instrument,
    Limits,
    Run,
    equal_weights,
    run,
)
from autotrading.domain.factors import Dividend
from autotrading.domain.fair_value import month_ends
from autotrading.domain.momentum import MomentumRuleSet, MomentumRulesFile, assess
from autotrading.domain.risk import Bar
from autotrading.domain.rotation import SnapshotInput
from autotrading.domain.splits import NEW_YORK, Split
from autotrading.repositories.audit import set_actor
from autotrading.repositories.factors import targets
from autotrading.repositories.prices import daily_bars, instruments_by_symbol
from autotrading.repositories.risk import stored_risk_rules
from autotrading.repositories.rotation import snapshot_input, stored_rotation_rules
from autotrading.settings import get_settings

ACTOR = "rules:backtest_rules"
HISTORY_START = datetime(2016, 1, 1, tzinfo=NEW_YORK)  # closes, splits and dividends (ADR-030)
STRATEGIES = ("S1", "S3", "S4")


def load_backtest_rules(path: Path | None = None) -> BacktestRulesFile:
    path = path or get_settings().resolved_config_dir() / "backtest_rules.yaml"
    return BacktestRulesFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_momentum_rules(path: Path | None = None) -> MomentumRulesFile:
    path = path or get_settings().resolved_config_dir() / "momentum_rules.yaml"
    return MomentumRulesFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache
def _backtest_file() -> BacktestRulesFile:
    return load_backtest_rules()


@lru_cache
def _momentum_file() -> MomentumRulesFile:
    return load_momentum_rules()


def active_backtest_version() -> str:
    return _backtest_file().active().rule_version


def active_momentum_version() -> str:
    return _momentum_file().active().rule_version


def stored_backtest_rules(
    session: Session, rule_version: str | None = None
) -> BacktestRuleSet | None:
    """A released backtest rule set as `make migrate` registered it; None when not loaded."""
    version = rule_version or active_backtest_version()
    row = session.scalars(
        select(BacktestRuleSetRow).where(BacktestRuleSetRow.rule_version == version)
    ).first()
    return BacktestRuleSet.model_validate(row.content) if row else None


def stored_momentum_rules(
    session: Session, rule_version: str | None = None
) -> MomentumRuleSet | None:
    version = rule_version or active_momentum_version()
    row = session.scalars(
        select(MomentumRuleSetRow).where(MomentumRuleSetRow.rule_version == version)
    ).first()
    return MomentumRuleSet.model_validate(row.content) if row else None


# ---------- market ----------


def instruments_at(
    session: Session,
    symbols: Iterable[str],
    sectors: dict[str, str],
    at: datetime,
    system_time: datetime,
) -> dict[str, Instrument]:
    """Each instrument's raw end-of-day bars since 2016, splits and dividends known at (T, S)."""
    out: dict[str, Instrument] = {}
    for target in targets(session, sorted(set(symbols))):
        instrument_id = target.instrument.id
        bars = [
            Bar(b.bar_date, b.close, Decimal(b.volume or 0), b.feed_status, b.published_at)
            for b in daily_bars(
                session,
                instrument_id,
                "raw",
                since=HISTORY_START,
                until=at,
                known_at=at,
                system_time=system_time,
            )
        ]
        splits = [
            Split(s.ex_date, s.old_rate, s.new_rate)
            for s in session.scalars(
                select(SplitEvent)
                .where(
                    SplitEvent.instrument_id == instrument_id,
                    SplitEvent.published_at <= at,
                    recorded_by(SplitEvent.recorded_at, system_time),
                )
                .order_by(SplitEvent.ex_date)
            )
        ]
        dividends = [
            Dividend(d.ex_date, d.rate, d.special)
            for d in session.scalars(
                select(DividendEvent)
                .where(
                    DividendEvent.instrument_id == instrument_id,
                    DividendEvent.published_at <= at,
                    recorded_by(DividendEvent.recorded_at, system_time),
                )
                .order_by(DividendEvent.ex_date, DividendEvent.special)
            )
        ]
        out[target.symbol] = Instrument(
            target.symbol, target.kind, bars, splits, dividends, sectors.get(target.symbol)
        )
    return out


def _snapshots(
    session: Session,
    definition_version: str,
    symbols: Sequence[str],
    at: datetime,
    system_time: datetime,
) -> dict[str, list[FactorSnapshot]]:
    """Each symbol's full factor snapshots (scope `all`: month ends and the daily ones since
    2026-10) known at T and recorded by S, oldest first."""
    ids = instruments_by_symbol(session, symbols)
    rows = session.scalars(
        select(FactorSnapshot)
        .where(
            FactorSnapshot.instrument_id.in_(ids.values()),
            FactorSnapshot.definition_version == definition_version,
            FactorSnapshot.scope == "all",
            FactorSnapshot.known_at <= at,
            FactorSnapshot.recorded_at <= system_time,
        )
        .order_by(FactorSnapshot.known_at)
    ).all()
    out: dict[str, list[FactorSnapshot]] = {s: [] for s in symbols}
    for row in rows:
        out.setdefault(row.symbol, []).append(row)
    return out


def _latest(rows: Sequence[FactorSnapshot], at: datetime) -> FactorSnapshot | None:
    found = None
    for row in rows:
        if row.known_at > at:
            break
        found = row
    return found


def _beta(row: FactorSnapshot | None) -> Decimal | None:
    value = row.measure_values.get("beta_252d") if row is not None else None
    return Decimal(str(value)) if value is not None else None


# ---------- events ----------


def s1_events(
    session: Session, rules: BacktestRuleSet, at: datetime, system_time: datetime
) -> list[Event]:
    spec = rules.strategies["S1"]
    stale = timedelta(days=spec.state_stale_after_days or 35)
    rows = session.scalars(
        select(BuybackStateAssignment)
        .where(
            BuybackStateAssignment.rule_version == spec.rule_version,
            BuybackStateAssignment.known_at <= at,
            BuybackStateAssignment.recorded_at <= system_time,
        )
        .order_by(BuybackStateAssignment.known_at)
    ).all()
    symbols = {v: k for k, v in instruments_by_symbol(session).items()}
    universe = [t.symbol for t in targets(session) if t.kind == "equity"]
    # betas from the factor definitions the S4 rules pin (the same snapshots)
    momentum = stored_momentum_rules(session, rules.strategies["S4"].rule_version)
    version = momentum.factor_definition_version if momentum else "0.1.0"
    snapshots = _snapshots(session, version, universe, at, system_time)
    events: list[Event] = []
    for point in month_ends(spec.since, at):
        latest: dict[str, BuybackStateAssignment] = {}
        for row in rows:
            if row.known_at > point:
                break
            if point - row.known_at <= stale:
                latest[symbols.get(row.instrument_id, row.ticker)] = row
        held = [s for s in universe if s in latest and latest[s].state in spec.holds]
        events.append(
            Event(
                at=point,
                weights=equal_weights(held),
                reason="month_start",
                source={"table": "buyback_state_assignments", "at": point.isoformat()},
                betas={s: _beta(_latest(snapshots.get(s, []), point)) for s in held},
            )
        )
    return events


def s3_events(
    session: Session, rules: BacktestRuleSet, at: datetime, system_time: datetime
) -> list[Event]:
    spec = rules.strategies["S3"]
    rotation = stored_rotation_rules(session, spec.rule_version)
    order = rotation.sleeves.universe() if rotation else []
    since = datetime.combine(spec.since, datetime.min.time(), tzinfo=NEW_YORK)
    rows = session.scalars(
        select(RotationAssessment)
        .where(
            RotationAssessment.rule_version == spec.rule_version,
            RotationAssessment.rebalance,
            RotationAssessment.known_at >= since,
            RotationAssessment.known_at <= at,
            RotationAssessment.recorded_at <= system_time,
        )
        .order_by(RotationAssessment.known_at)
    ).all()
    events: list[Event] = []
    for row in rows:
        target = row.target or {}
        readings = {r["symbol"]: r for r in row.assessment.get("readings", [])}
        symbols = sorted(target, key=lambda s: order.index(s) if s in order else len(order))
        events.append(
            Event(
                at=row.known_at,
                weights={s: Decimal(target[s]) for s in symbols},
                reason=row.reason,
                source={"table": "rotation_assessments", "id": str(row.id)},
                betas={
                    s: Decimal(str(readings[s]["beta"]))
                    if s in readings and readings[s].get("beta") is not None
                    else None
                    for s in symbols
                },
            )
        )
    return events


def s4_events(
    session: Session, rules: BacktestRuleSet, at: datetime, system_time: datetime
) -> list[Event]:
    spec = rules.strategies["S4"]
    momentum = stored_momentum_rules(session, spec.rule_version)
    if momentum is None:
        return []
    if spec.targets_from == "momentum_assessments":
        return _s4_assessed(
            session, spec.since, spec.rule_version, momentum.universe, at, system_time
        )
    snapshots = _snapshots(
        session, momentum.factor_definition_version, momentum.universe, at, system_time
    )
    events: list[Event] = []
    for point in month_ends(spec.since, at):
        found = {s: _latest(rows, point) for s, rows in snapshots.items()}
        inputs: dict[str, SnapshotInput] = {
            s: snapshot_input(row) for s, row in found.items() if row is not None
        }
        result = assess(momentum, point, inputs)
        events.append(
            Event(
                at=point,
                weights=result.target,
                reason="month_start",
                source={"table": "factor_snapshots", "at": point.isoformat()},
                betas={s: _beta(found.get(s)) for s in result.target},
            )
        )
    return events


def _s4_assessed(
    session: Session,
    since_day: date,
    rule_version: str,
    universe: Sequence[str],
    at: datetime,
    system_time: datetime,
) -> list[Event]:
    """Every S4 target set by the stored daily assessments known at T and recorded by S."""
    since = datetime.combine(since_day, datetime.min.time(), tzinfo=NEW_YORK)
    rows = session.scalars(
        select(MomentumAssessment)
        .where(
            MomentumAssessment.rule_version == rule_version,
            MomentumAssessment.rebalance,
            MomentumAssessment.known_at >= since,
            MomentumAssessment.known_at <= at,
            MomentumAssessment.recorded_at <= system_time,
        )
        .order_by(MomentumAssessment.known_at)
    ).all()
    events: list[Event] = []
    for row in rows:
        target = row.target or {}
        readings = {r["symbol"]: r for r in row.assessment.get("readings", [])}
        symbols = [s for s in universe if s in target]
        snapshot_ids = [readings[s]["snapshot_id"] for s in symbols if s in readings]
        found = {
            s.symbol: s
            for s in session.scalars(
                select(FactorSnapshot).where(FactorSnapshot.id.in_(snapshot_ids))
            )
        }
        events.append(
            Event(
                at=row.known_at,
                weights={s: Decimal(target[s]) for s in symbols},
                reason=row.reason,
                source={"table": "momentum_assessments", "id": str(row.id)},
                betas={s: _beta(found.get(s)) for s in symbols},
            )
        )
    return events


EVENTS = {"S1": s1_events, "S3": s3_events, "S4": s4_events}


# ---------- runs ----------


def _limits(session: Session, rules: BacktestRuleSet) -> tuple[Limits | None, dict[str, str]]:
    risk = stored_risk_rules(session, rules.risk_rule_version)
    if risk is None:
        return None, {}
    limits = Limits(
        rule_version=risk.rule_version,
        position_pct=risk.limits.position_pct,
        sector_pct=risk.limits.sector_pct,
        gross_pct=risk.limits.gross_pct,
        volume_pct=risk.limits.volume_pct,
        volume_sessions=risk.limits.volume_sessions,
        unlimited_sectors=frozenset(risk.unlimited_sectors),
    )
    return limits, {s: e.sector for s, e in risk.sectors.items()}


NOTES_0_1_0 = {
    "S1": [
        "Buyback states exist at month ends since 2021 only.",
        "TRADE-READY read the standard risk check against the journal's book at T, which was "
        "empty, so it almost always passed (KI-13).",
    ],
    "S3": [
        "The month-end history cannot show a defensive switch (KI-17); daily assessments "
        "start in October 2026.",
        "The 8 ETFs were chosen today (KI-16).",
    ],
    "S4": [
        "12-1 momentum starts in 2017. S4 makes no live signal yet.",
        "Only today's 10 companies: no delisted company (KI-1).",
    ],
}
# Each backtest rule version's notes are part of its stored runs, so they never change.
NOTES = {
    "0.1.0": NOTES_0_1_0,
    "0.2.0": {
        "S1": NOTES_0_1_0["S1"],
        "S3": [
            "Assessed at every session since 2017 under regime rules 0.2.0 (ADR-036): defensive "
            "switches inside a month are in the history.",
            "The 8 ETFs were chosen today (KI-16).",
        ],
        "S4": [
            "12-1 momentum starts in 2017; the targets are the stored daily S4 assessments, set "
            "at the first assessment of each month (ADR-036 D7).",
            "Only today's 10 companies: no delisted company (KI-1).",
        ],
    },
}


def run_strategy(
    session: Session,
    rules: BacktestRuleSet,
    strategy_id: str,
    at: datetime,
    system_time: datetime,
) -> Run:
    """One strategy's backtest at (T, S) from stored rows only."""
    events = EVENTS[strategy_id](session, rules, at, system_time)
    limits, sectors = _limits(session, rules)
    symbols = {rules.benchmark} | {s for e in events for s in e.weights}
    instruments = instruments_at(session, symbols, sectors, at, system_time)
    return run(
        rules, strategy_id, at, events, instruments, limits, NOTES[rules.rule_version][strategy_id]
    )


def record_run(
    session: Session,
    rules: BacktestRuleSet,
    strategy_id: str,
    at: datetime,
    system_time: datetime,
    trigger: Literal["schedule", "manual", "backfill", "replay"],
) -> BacktestRun | None:
    """Store one strategy's run; None when this T and these versions have one."""
    set_actor(session, ACTOR)
    result = run_strategy(session, rules, strategy_id, at, system_time)
    return session.scalars(
        insert(BacktestRun)
        .values(
            known_at=at,
            system_time=system_time,
            rule_version=rules.rule_version,
            strategy_id=strategy_id,
            strategy_rule_version=result.strategy_rule_version,
            start=result.start,
            end=result.end,
            trigger=trigger,
            performance_reported=False,
            document=result.model_dump(mode="json"),
        )
        .on_conflict_do_nothing(constraint="uq_backtest_runs_point")
        .returning(BacktestRun)
    ).first()


def record_all(
    session: Session,
    rules: BacktestRuleSet,
    at: datetime,
    system_time: datetime,
    trigger: Literal["schedule", "manual", "backfill", "replay"],
) -> list[BacktestRun]:
    """Every strategy's run at (T, S), committing after each."""
    stored: list[BacktestRun] = []
    for strategy_id in STRATEGIES:
        row = record_run(session, rules, strategy_id, at, system_time, trigger)
        session.commit()
        if row is not None:
            stored.append(row)
    return stored


def ran_this_month(session: Session, rules: BacktestRuleSet, at: datetime) -> bool:
    """Whether a run under these rules is known in T's New York month (the monthly schedule)."""
    local = at.astimezone(NEW_YORK)
    start = datetime(local.year, local.month, 1, tzinfo=NEW_YORK)
    count = session.scalar(
        select(func.count())
        .select_from(BacktestRun)
        .where(
            BacktestRun.rule_version == rules.rule_version,
            BacktestRun.known_at >= start,
            BacktestRun.known_at <= at,
        )
    )
    return bool(count)


def recompute(session: Session, row: BacktestRun) -> Run | None:
    """A stored run recomputed with its own T, S and rule versions."""
    rules = stored_backtest_rules(session, row.rule_version)
    if rules is None:
        return None
    return run_strategy(session, rules, row.strategy_id, row.known_at, row.system_time)


def same(row: BacktestRun, result: Run) -> bool:
    return bool(result.model_dump(mode="json") == row.document)


def latest_runs(session: Session, rule_version: str, at: datetime) -> list[BacktestRun]:
    """Each strategy's latest run known at T under one backtest rule version."""
    return list(
        session.scalars(
            select(BacktestRun)
            .where(BacktestRun.rule_version == rule_version, BacktestRun.known_at <= at)
            .ext(distinct_on(BacktestRun.strategy_id))
            .order_by(BacktestRun.strategy_id, BacktestRun.known_at.desc())
        ).all()
    )
