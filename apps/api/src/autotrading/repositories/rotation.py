"""S3 ETF rotation (M2.4, ADR-032): the stored regime assessment and factor snapshots known at
(T, S) under the versions the rules name, and the rows a rotation produces, in the caller's
transaction.

`record_rotation` stores one assessment per T and rule version, the S3 signals of a newly set
target, and an alert when the target changed (under the active alert rules, if they ask for
it). The previous target is the latest stored assessment before T that had one, as the
database held it at S; a backfill passes the previous point of its own run instead (its rows
were recorded after its S, from inputs known at S). Re-running is harmless.
"""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import cast
from uuid import UUID

import yaml
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from autotrading.db.models import FactorSnapshot, RegimeAssessment, RotationAssessment
from autotrading.db.models import RotationRuleSet as RotationRuleSetRow
from autotrading.domain.rotation import (
    MeasureInput,
    PreviousTarget,
    RegimeInput,
    Rotation,
    RotationRuleSet,
    RotationRulesFile,
    SnapshotInput,
    StressState,
    assess,
    rotation_alert,
    signals,
)
from autotrading.repositories.audit import set_actor
from autotrading.repositories.convergence import insert_alert, stored_alert_rules
from autotrading.repositories.prices import instruments_by_symbol
from autotrading.repositories.signals import record_signal
from autotrading.settings import get_settings

ACTOR = "rules:rotation_rules"
LOOKUP = "lookup"  # record_rotation: find the previous target in the database


def load_rotation_rules(path: Path | None = None) -> RotationRulesFile:
    path = path or get_settings().resolved_config_dir() / "rotation_rules.yaml"
    return RotationRulesFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache
def _file() -> RotationRulesFile:
    return load_rotation_rules()


def active_rotation_version() -> str:
    return _file().active().rule_version


def stored_rotation_rules(
    session: Session, rule_version: str | None = None
) -> RotationRuleSet | None:
    """A released rotation rule set as `make migrate` registered it; None when not loaded."""
    version = rule_version or active_rotation_version()
    row = session.scalars(
        select(RotationRuleSetRow).where(RotationRuleSetRow.rule_version == version)
    ).first()
    return RotationRuleSet.model_validate(row.content) if row else None


# ---------- inputs ----------


def regime_input(
    session: Session, rules: RotationRuleSet, at: datetime, system_time: datetime
) -> RegimeInput | None:
    """The latest regime assessment known at T and recorded by S, under the pinned version."""
    row = session.scalars(
        select(RegimeAssessment)
        .where(
            RegimeAssessment.rule_version == rules.regime_rule_version,
            RegimeAssessment.known_at <= at,
            RegimeAssessment.recorded_at <= system_time,
        )
        .order_by(RegimeAssessment.known_at.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    return RegimeInput(
        id=str(row.id),
        known_at=row.known_at,
        rule_version=row.rule_version,
        stress=cast(StressState | None, row.stress),  # CHECKed against the stress states
        quadrant=row.quadrant,
        stress_detail=str(row.assessment.get("stress_detail", "")),
    )


def snapshot_input(row: FactorSnapshot) -> SnapshotInput:
    measures: dict[str, MeasureInput] = {}
    for m in row.snapshot.get("measures", []):
        value = m.get("value")
        measures[m["measure_id"]] = MeasureInput(
            value=None if value is None else Decimal(str(value)), detail=str(m.get("detail", ""))
        )
    return SnapshotInput(
        id=str(row.id),
        symbol=row.symbol,
        known_at=row.known_at,
        definition_version=row.definition_version,
        last_close=row.last_close,
        feed_status=row.feed_status,
        measures=measures,
    )


def snapshot_inputs(
    session: Session, rules: RotationRuleSet, at: datetime, system_time: datetime
) -> dict[str, SnapshotInput]:
    """Each ETF's latest factor snapshot known at T and recorded by S, under the pinned
    definition version."""
    ids = instruments_by_symbol(session, rules.sleeves.universe())
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


def previous_target(row: RotationAssessment) -> PreviousTarget:
    assert row.target is not None
    stored = row.assessment
    return PreviousTarget(
        id=str(row.id),
        known_at=row.known_at,
        stress=cast(StressState | None, row.stress),  # CHECKed against the stress states
        target={symbol: Decimal(weight) for symbol, weight in row.target.items()},
        set_at=datetime.fromisoformat(stored["set_at"]),
    )


def previous_at(
    session: Session, rules: RotationRuleSet, at: datetime, system_time: datetime
) -> RotationAssessment | None:
    """The latest assessment before T that had a target, as the database held it at S."""
    return session.scalars(
        select(RotationAssessment)
        .where(
            RotationAssessment.rule_version == rules.rule_version,
            RotationAssessment.known_at < at,
            RotationAssessment.target.is_not(None),
            RotationAssessment.recorded_at <= system_time,
        )
        .order_by(RotationAssessment.known_at.desc())
        .limit(1)
    ).first()


def rotation_at(
    session: Session,
    rules: RotationRuleSet,
    at: datetime,
    system_time: datetime,
    previous: RotationAssessment | None,
) -> Rotation:
    return assess(
        rules,
        at,
        regime_input(session, rules, at, system_time),
        snapshot_inputs(session, rules, at, system_time),
        previous_target(previous) if previous is not None else None,
    )


# ---------- writing ----------


def _target(rotation: Rotation) -> dict[str, str] | None:
    if rotation.target is None:
        return None
    return {h.symbol: str(h.weight_pct) for h in rotation.target}


def record_rotation(
    session: Session,
    rules: RotationRuleSet,
    at: datetime,
    system_time: datetime,
    trigger: str,
    previous: RotationAssessment | str | None = LOOKUP,
) -> RotationAssessment | None:
    """Store the rotation at T, the signals of a newly set target and an alert when it
    changed; None when T is assessed already. `previous` overrides the lookup (a backfill
    passes the previous row of its own run)."""
    set_actor(session, ACTOR)
    before = previous_at(session, rules, at, system_time) if isinstance(previous, str) else previous
    rotation = rotation_at(session, rules, at, system_time, before)
    backfilled = system_time > at
    row = session.scalars(
        insert(RotationAssessment)
        .values(
            known_at=at,
            system_time=system_time,
            rule_version=rules.rule_version,
            stress=rotation.stress,
            rebalance=rotation.rebalance,
            reason=rotation.reason,
            target=_target(rotation),
            previous_id=before.id if before is not None else None,
            assessment=rotation.model_dump(mode="json"),
            backfilled=backfilled,
            trigger=trigger,
        )
        .on_conflict_do_nothing(constraint="uq_rotation_assessments_known_at_rule")
        .returning(RotationAssessment)
    ).first()
    if row is None:
        return None
    ids = instruments_by_symbol(session, rules.sleeves.universe())
    for symbol, signal in signals(rotation, str(row.id), system_time):
        if symbol in ids:
            record_signal(session, ids[symbol], symbol, signal)
    alert_rules = stored_alert_rules(session)
    if (
        alert_rules is not None
        and "target_change" in alert_rules.rotation_events
        and alert_rules.rotation_rule_version == rules.rule_version
    ):
        weights = previous_target(before).target if before is not None else None
        found = rotation_alert(rotation, weights, str(row.id))
        if found is not None:
            insert_alert(session, alert_rules, None, None, found, system_time, None, backfilled)
    return row


def stored_at(session: Session, rules: RotationRuleSet, at: datetime) -> RotationAssessment | None:
    return session.scalars(
        select(RotationAssessment).where(
            RotationAssessment.rule_version == rules.rule_version, RotationAssessment.known_at == at
        )
    ).first()


def record_points(
    session: Session,
    rules: RotationRuleSet,
    points: Sequence[datetime],
    system_time: datetime,
    trigger: str,
) -> int:
    """Assess each point in order, all at one system time, each comparing with the previous
    point of the run that had a target (a backfill or the CI replay); returns how many were
    stored. Commits after each point."""
    ordered = sorted(points)
    previous = previous_at(session, rules, ordered[0], system_time) if ordered else None
    stored = 0
    for at in ordered:
        row = record_rotation(session, rules, at, system_time, trigger, previous=previous)
        if row is None:
            row = stored_at(session, rules, at)
        else:
            stored += 1
        session.commit()
        if row is not None and row.target is not None:
            previous = row
    return stored


def raise_alerts(session: Session, rules: RotationRuleSet, system_time: datetime) -> int:
    """The target-change alerts of every stored assessment under the active alert rules, in
    order of T (for `make alerts-backfill` after a new alert rule version); returns how many
    were new."""
    alert_rules = stored_alert_rules(session)
    if (
        alert_rules is None
        or "target_change" not in alert_rules.rotation_events
        or alert_rules.rotation_rule_version != rules.rule_version
    ):
        return 0
    rows = session.scalars(
        select(RotationAssessment)
        .where(RotationAssessment.rule_version == rules.rule_version, RotationAssessment.rebalance)
        .order_by(RotationAssessment.known_at)
    ).all()
    previous = {r.id: r for r in session.scalars(select(RotationAssessment)).all()}
    raised = 0
    for row in rows:
        before = previous.get(row.previous_id) if row.previous_id else None
        weights = previous_target(before).target if before is not None else None
        rotation = Rotation.model_validate(row.assessment)
        found = rotation_alert(rotation, weights, str(row.id))
        if found is not None:
            raised += insert_alert(session, alert_rules, None, None, found, system_time, None, True)
    return raised


def recompute(session: Session, row: RotationAssessment) -> Rotation | None:
    """A stored assessment recomputed with its own T, S, rule version and previous target."""
    rules = stored_rotation_rules(session, row.rule_version)
    if rules is None:
        return None
    before = session.get(RotationAssessment, row.previous_id) if row.previous_id else None
    return rotation_at(session, rules, row.known_at, row.system_time, before)


def same(row: RotationAssessment, rotation: Rotation) -> bool:
    return bool(rotation.model_dump(mode="json") == row.assessment)


def assessments(
    session: Session, rules: RotationRuleSet, at: datetime
) -> Sequence[RotationAssessment]:
    """Every stored assessment known at T, oldest first."""
    return session.scalars(
        select(RotationAssessment)
        .where(
            RotationAssessment.rule_version == rules.rule_version, RotationAssessment.known_at <= at
        )
        .order_by(RotationAssessment.known_at)
    ).all()


def latest(session: Session, rules: RotationRuleSet, at: datetime) -> RotationAssessment | None:
    return session.scalars(
        select(RotationAssessment)
        .where(
            RotationAssessment.rule_version == rules.rule_version, RotationAssessment.known_at <= at
        )
        .order_by(RotationAssessment.known_at.desc())
        .limit(1)
    ).first()


def set_rules_actor(session: Session) -> None:
    set_actor(session, ACTOR)


def instrument_ids(session: Session, rules: RotationRuleSet) -> dict[str, UUID]:
    return instruments_by_symbol(session, rules.sleeves.universe())
