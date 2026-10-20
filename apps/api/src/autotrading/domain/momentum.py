"""Medium-term momentum, strategy S4 (M2.5, ADR-033; 02 §13, §18). Pure; no I/O.

Each company of the universe is judged against its own history and SPY only (no ranking across
companies: P2-3, KI-1). It is selected when every condition of its factor snapshot is above its
threshold (12-1 momentum and 12-1 momentum against SPY, rules 0.1.0). The selected companies are
held in equal weights, rounded down; the rest is cash. No stress gate (S3's job). The target
changes at the first assessment of each New York month and is carried otherwise (`daily`,
M3.0, ADR-036 D7); backtest rules 0.1.0 assessed month ends with `assess`.

Research only: paper signals (family 5) when a target is set, no order; backtests withhold
performance (OD-7).
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from autotrading.domain.rotation import SnapshotInput, TrendCondition, TrendReading
from autotrading.domain.signals import SOURCE_QUALITY, SignalIn
from autotrading.domain.splits import NEW_YORK

STRATEGY = "S4"  # Medium-term Momentum
TREND_FAMILY = 5  # Price / Trend / Factor (domain/registries.py)
HUNDRED = Decimal(100)
Reason = Literal["month_start", "carried", "unavailable"]


class _Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MomentumRuleSet(_Rule):
    """One released rule version: immutable, like the rotation rule sets (ADR-032)."""

    rule_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    released: date
    note: str
    factor_definition_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    universe: Annotated[list[str], Field(min_length=1)]
    conditions: Annotated[list[TrendCondition], Field(min_length=1)]
    weight_quantum_pct: Annotated[Decimal, Field(gt=0)]
    factor_stale_after_days: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def _distinct(self) -> "MomentumRuleSet":
        if len(self.universe) != len(set(self.universe)):
            raise ValueError("a company is listed twice")
        return self

    def content(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"status"}, exclude_defaults=True)

    def content_sha256(self) -> str:
        canonical = json.dumps(self.content(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class MomentumRuleSetEntry(MomentumRuleSet):
    status: Literal["active", "retired"]

    def rule_set(self) -> MomentumRuleSet:
        return MomentumRuleSet.model_validate(self.content())


class MomentumRulesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    rule_sets: list[MomentumRuleSetEntry]

    @model_validator(mode="after")
    def _one_active(self) -> "MomentumRulesFile":
        versions = [r.rule_version for r in self.rule_sets]
        if len(versions) != len(set(versions)):
            raise ValueError("duplicate rule_version")
        if sum(r.status == "active" for r in self.rule_sets) != 1:
            raise ValueError("exactly one rule set must be active")
        return self

    def active(self) -> MomentumRuleSet:
        return next(r.rule_set() for r in self.rule_sets if r.status == "active")


class CompanyReading(BaseModel):
    symbol: str
    snapshot_id: str | None
    snapshot_known_at: datetime | None
    conditions: list[TrendReading]
    selected: bool
    detail: str


class Momentum(BaseModel):
    """S4 at T: every company's reading and the equal-weight target."""

    rule_version: str
    known_at: datetime
    readings: list[CompanyReading]
    target: dict[str, Decimal]  # symbol -> weight in percent, universe order
    cash_pct: Decimal


def read_company(
    rules: MomentumRuleSet, at: datetime, symbol: str, snapshot: SnapshotInput | None
) -> CompanyReading:
    stale = snapshot is not None and at - snapshot.known_at > timedelta(
        days=rules.factor_stale_after_days
    )
    if snapshot is None or stale:
        return CompanyReading(
            symbol=symbol,
            snapshot_id=snapshot.id if snapshot else None,
            snapshot_known_at=snapshot.known_at if snapshot else None,
            conditions=[],
            selected=False,
            detail="no factor snapshot known at T"
            if snapshot is None
            else f"the factor snapshot of {snapshot.known_at.date()} is older than "
            f"{rules.factor_stale_after_days} days",
        )
    readings: list[TrendReading] = []
    for condition in rules.conditions:
        measure = snapshot.measures.get(condition.measure)
        if measure is None or measure.value is None:
            readings.append(
                TrendReading(
                    measure=condition.measure,
                    value=None,
                    threshold=condition.above,
                    status="unavailable",
                    detail=measure.detail if measure else "not in the factor snapshot",
                )
            )
            continue
        passed = measure.value > condition.above
        readings.append(
            TrendReading(
                measure=condition.measure,
                value=measure.value,
                threshold=condition.above,
                status="pass" if passed else "fail",
                detail=f"{measure.value} {'>' if passed else '<='} {condition.above}",
            )
        )
    selected = all(r.status == "pass" for r in readings)
    failed = [r.measure for r in readings if r.status != "pass"]
    return CompanyReading(
        symbol=symbol,
        snapshot_id=snapshot.id,
        snapshot_known_at=snapshot.known_at,
        conditions=readings,
        selected=selected,
        detail="selected" if selected else "not selected: " + ", ".join(failed),
    )


def assess(
    rules: MomentumRuleSet, at: datetime, snapshots: Mapping[str, SnapshotInput]
) -> Momentum:
    """The S4 target at T from the factor snapshots known then (ADR-033 B3)."""
    readings = [read_company(rules, at, s, snapshots.get(s)) for s in rules.universe]
    chosen = [r.symbol for r in readings if r.selected]
    target: dict[str, Decimal] = {}
    if chosen:
        weight = (HUNDRED / len(chosen)).quantize(rules.weight_quantum_pct, rounding=ROUND_DOWN)
        target = {s: weight for s in chosen}
    return Momentum(
        rule_version=rules.rule_version,
        known_at=at,
        readings=readings,
        target=target,
        cash_pct=HUNDRED - sum(target.values(), Decimal(0)),
    )


# ---------- daily assessment (M3.0, ADR-036 D7) ----------


@dataclass(frozen=True)
class PreviousMomentum:
    """The latest stored S4 assessment before T that had a target."""

    id: str
    known_at: datetime
    target: Mapping[str, Decimal]  # symbol -> weight in percent
    set_at: datetime  # when that target was set


class MomentumAssessment(BaseModel):
    """Everything a stored S4 assessment holds: recomputing it gives the same document."""

    rule_version: str
    known_at: datetime
    readings: list[CompanyReading]
    rebalance: bool
    reason: Reason
    detail: str
    previous_id: str | None
    set_at: datetime | None  # when the target in force was set
    target: dict[str, Decimal] | None  # universe order; None when unavailable
    cash_pct: Decimal | None


def _ny_month(at: datetime) -> tuple[int, int]:
    local = at.astimezone(NEW_YORK)
    return local.year, local.month


def daily(
    rules: MomentumRuleSet,
    at: datetime,
    snapshots: Mapping[str, SnapshotInput],
    previous: PreviousMomentum | None,
) -> MomentumAssessment:
    """S4 at T: a new target at the first assessment of each New York month, the previous one
    carried otherwise; unavailable when no company has a factor snapshot fresh at T."""
    found = assess(rules, at, snapshots)

    def result(
        reason: Reason, detail: str, set_at: datetime | None, target: dict[str, Decimal] | None
    ) -> MomentumAssessment:
        return MomentumAssessment(
            rule_version=rules.rule_version,
            known_at=at,
            readings=found.readings,
            rebalance=reason == "month_start",
            reason=reason,
            detail=detail,
            previous_id=previous.id if previous else None,
            set_at=set_at,
            target=target,
            cash_pct=None if target is None else HUNDRED - sum(target.values(), Decimal(0)),
        )

    if not any(r.conditions for r in found.readings):
        return result("unavailable", "no company has a factor snapshot fresh at T", None, None)
    if previous is None or _ny_month(at) != _ny_month(previous.known_at):
        held = ", ".join(found.target) or "cash only"
        return result("month_start", f"first assessment of the month: {held}", at, found.target)
    carried = {s: previous.target[s] for s in rules.universe if s in previous.target}
    since = previous.set_at.astimezone(NEW_YORK).date()
    return result("carried", f"target of {since} carried", previous.set_at, carried)


def signals(
    momentum: MomentumAssessment, assessment_id: str, system_time: datetime
) -> list[tuple[str, SignalIn]]:
    """(symbol, signal) for each company of a newly set target: family 5, scored by its first
    condition's value (12-1 momentum), citing the assessment and the factor snapshot it read.
    None when carried or unavailable."""
    if not momentum.rebalance or not momentum.target:
        return []
    by_symbol = {r.symbol: r for r in momentum.readings}
    out: list[tuple[str, SignalIn]] = []
    for symbol in momentum.target:
        reading = by_symbol[symbol]
        out.append(
            (
                symbol,
                SignalIn(
                    family_id=TREND_FAMILY,
                    strategy_id=STRATEGY,
                    rule_version=momentum.rule_version,
                    score=reading.conditions[0].value if reading.conditions else None,
                    direction="long",
                    generated_at=momentum.known_at,
                    valid_from=momentum.known_at,
                    system_time=system_time,
                    observation_ids=[
                        {"table": "momentum_assessments", "id": assessment_id},
                        {"table": "factor_snapshots", "id": reading.snapshot_id or ""},
                    ],
                    source_quality=SOURCE_QUALITY,
                    evidence_independence=sum(r.status == "pass" for r in reading.conditions),
                    execution_eligibility="paper_only",
                    backfilled=system_time > momentum.known_at,
                ),
            )
        )
    return out
