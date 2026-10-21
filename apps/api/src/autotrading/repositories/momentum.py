"""Strategy S4's daily assessment (M3.0, ADR-036 D7): the factor snapshots known at (T, S) under
the version the momentum rules name, and the rows an assessment produces, in the caller's
transaction.

`record_momentum` stores one assessment per T and rule version, the S4 signals of a newly set
target and, since M3.0b (ADR-037), an alert when the target changed (under the active alert
rules, if they ask for it). The previous target is the latest stored assessment before T that
had one, as the database held it at S; a backfill passes the previous point of its own run
instead (its rows were recorded after its S, from inputs known at S). Re-running is harmless.
"""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from sqlalchemy import null, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from autotrading.db.models import FactorSnapshot, MomentumAssessment
from autotrading.domain.momentum import MomentumAssessment as Assessment
from autotrading.domain.momentum import (
    MomentumRuleSet,
    PreviousMomentum,
    daily,
    momentum_alert,
    signals,
)
from autotrading.domain.rotation import SnapshotInput
from autotrading.repositories.audit import set_actor
from autotrading.repositories.backtest import stored_momentum_rules
from autotrading.repositories.convergence import insert_alert, stored_alert_rules
from autotrading.repositories.prices import instruments_by_symbol
from autotrading.repositories.rotation import snapshot_input
from autotrading.repositories.signals import record_signal

ACTOR = "rules:momentum_rules"
LOOKUP = "lookup"  # record_momentum: find the previous target in the database


# ---------- inputs ----------


def snapshot_inputs(
    session: Session, rules: MomentumRuleSet, at: datetime, system_time: datetime
) -> dict[str, SnapshotInput]:
    """Each company's latest factor snapshot known at T and recorded by S, under the pinned
    definition version (either scope: both hold the price measures S4 reads)."""
    ids = instruments_by_symbol(session, rules.universe)
    out: dict[str, SnapshotInput] = {}
    for symbol, instrument_id in ids.items():
        row = session.scalars(
            select(FactorSnapshot)
            .where(
                FactorSnapshot.instrument_id == instrument_id,
                FactorSnapshot.definition_version == rules.factor_definition_version,
                FactorSnapshot.known_at <= at,
                FactorSnapshot.recorded_at <= system_time,
            )
            .order_by(FactorSnapshot.known_at.desc())
            .limit(1)
        ).first()
        if row is not None:
            out[symbol] = snapshot_input(row)
    return out


def previous_momentum(row: MomentumAssessment) -> PreviousMomentum:
    assert row.target is not None
    return PreviousMomentum(
        id=str(row.id),
        known_at=row.known_at,
        target={symbol: Decimal(weight) for symbol, weight in row.target.items()},
        set_at=datetime.fromisoformat(row.assessment["set_at"]),
    )


def previous_at(
    session: Session, rules: MomentumRuleSet, at: datetime, system_time: datetime
) -> MomentumAssessment | None:
    """The latest assessment before T that had a target, as the database held it at S."""
    return session.scalars(
        select(MomentumAssessment)
        .where(
            MomentumAssessment.rule_version == rules.rule_version,
            MomentumAssessment.known_at < at,
            MomentumAssessment.target.is_not(None),
            MomentumAssessment.recorded_at <= system_time,
        )
        .order_by(MomentumAssessment.known_at.desc())
        .limit(1)
    ).first()


def momentum_at(
    session: Session,
    rules: MomentumRuleSet,
    at: datetime,
    system_time: datetime,
    previous: MomentumAssessment | None,
) -> Assessment:
    return daily(
        rules,
        at,
        snapshot_inputs(session, rules, at, system_time),
        previous_momentum(previous) if previous is not None else None,
    )


# ---------- writing ----------


def record_momentum(
    session: Session,
    rules: MomentumRuleSet,
    at: datetime,
    system_time: datetime,
    trigger: str,
    previous: MomentumAssessment | str | None = LOOKUP,
) -> MomentumAssessment | None:
    """Store S4 at T and the signals of a newly set target; None when T is assessed already.
    `previous` overrides the lookup (a backfill passes the previous row of its own run)."""
    set_actor(session, ACTOR)
    before = previous_at(session, rules, at, system_time) if isinstance(previous, str) else previous
    found = momentum_at(session, rules, at, system_time, before)
    row = session.scalars(
        insert(MomentumAssessment)
        .values(
            known_at=at,
            system_time=system_time,
            rule_version=rules.rule_version,
            rebalance=found.rebalance,
            reason=found.reason,
            # SQL NULL when unavailable (a plain None would store JSON null)
            target={s: str(w) for s, w in found.target.items()}
            if found.target is not None
            else null(),
            previous_id=before.id if before is not None else None,
            assessment=found.model_dump(mode="json"),
            backfilled=system_time > at,
            trigger=trigger,
        )
        .on_conflict_do_nothing(constraint="uq_momentum_assessments_known_at_rule")
        .returning(MomentumAssessment)
    ).first()
    if row is None:
        return None
    ids = instruments_by_symbol(session, rules.universe)
    for symbol, signal in signals(found, str(row.id), system_time):
        if symbol in ids:
            record_signal(session, ids[symbol], symbol, signal)
    alert_rules = stored_alert_rules(session)
    if (
        alert_rules is not None
        and "target_change" in alert_rules.momentum_events
        and alert_rules.momentum_rule_version == rules.rule_version
    ):
        weights = previous_momentum(before).target if before is not None else None
        alert = momentum_alert(found, weights, str(row.id))
        if alert is not None:
            insert_alert(
                session, alert_rules, None, None, alert, system_time, None, system_time > at
            )
    return row


def stored_at(session: Session, rules: MomentumRuleSet, at: datetime) -> MomentumAssessment | None:
    return session.scalars(
        select(MomentumAssessment).where(
            MomentumAssessment.rule_version == rules.rule_version, MomentumAssessment.known_at == at
        )
    ).first()


def record_points(
    session: Session,
    rules: MomentumRuleSet,
    points: Sequence[datetime],
    system_time: datetime,
    trigger: str,
) -> int:
    """Assess each point in order, all at one system time, each carrying the previous point of
    the run that had a target (a backfill or the CI replay); returns how many were stored.
    Commits after each point."""
    ordered = sorted(points)
    previous = previous_at(session, rules, ordered[0], system_time) if ordered else None
    stored = 0
    for at in ordered:
        row = record_momentum(session, rules, at, system_time, trigger, previous=previous)
        if row is None:
            row = stored_at(session, rules, at)
        else:
            stored += 1
        session.commit()
        if row is not None and row.target is not None:
            previous = row
    return stored


def raise_alerts(session: Session, rules: MomentumRuleSet, system_time: datetime) -> int:
    """The target-change alerts of every stored assessment under the active alert rules, in
    order of T (for `make alerts-backfill` after a new alert rule version); returns how many
    were new."""
    alert_rules = stored_alert_rules(session)
    if (
        alert_rules is None
        or "target_change" not in alert_rules.momentum_events
        or alert_rules.momentum_rule_version != rules.rule_version
    ):
        return 0
    rows = session.scalars(
        select(MomentumAssessment)
        .where(MomentumAssessment.rule_version == rules.rule_version, MomentumAssessment.rebalance)
        .order_by(MomentumAssessment.known_at)
    ).all()
    previous = {
        r.id: r
        for r in session.scalars(
            select(MomentumAssessment).where(MomentumAssessment.target.is_not(None))
        )
    }
    raised = 0
    for row in rows:
        before = previous.get(row.previous_id) if row.previous_id else None
        weights = previous_momentum(before).target if before is not None else None
        alert = momentum_alert(Assessment.model_validate(row.assessment), weights, str(row.id))
        if alert is not None:
            raised += insert_alert(session, alert_rules, None, None, alert, system_time, None, True)
    return raised


def recompute(session: Session, row: MomentumAssessment) -> Assessment | None:
    """A stored assessment recomputed with its own T, S, rule version and previous target."""
    rules = stored_momentum_rules(session, row.rule_version)
    if rules is None:
        return None
    before = session.get(MomentumAssessment, row.previous_id) if row.previous_id else None
    return momentum_at(session, rules, row.known_at, row.system_time, before)


def same(row: MomentumAssessment, again: Assessment) -> bool:
    return bool(again.model_dump(mode="json") == row.assessment)


# ---------- reading ----------


def latest(session: Session, rules: MomentumRuleSet, at: datetime) -> MomentumAssessment | None:
    return session.scalars(
        select(MomentumAssessment)
        .where(
            MomentumAssessment.rule_version == rules.rule_version, MomentumAssessment.known_at <= at
        )
        .order_by(MomentumAssessment.known_at.desc())
        .limit(1)
    ).first()


def rebalances(
    session: Session, rules: MomentumRuleSet, at: datetime
) -> Sequence[MomentumAssessment]:
    """Every stored assessment known at T that set a target, oldest first."""
    return session.scalars(
        select(MomentumAssessment)
        .where(
            MomentumAssessment.rule_version == rules.rule_version,
            MomentumAssessment.rebalance,
            MomentumAssessment.known_at <= at,
        )
        .order_by(MomentumAssessment.known_at)
    ).all()
