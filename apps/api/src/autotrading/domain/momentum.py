"""Medium-term momentum, strategy S4 (M2.5, ADR-033; 02 §13, §18). Pure; no I/O.

Each company of the universe is judged against its own history and SPY only (no ranking across
companies: P2-3, KI-1). It is selected when every condition of its factor snapshot is above its
threshold (12-1 momentum and 12-1 momentum against SPY, rules 0.1.0). The selected companies are
held in equal weights, rounded down; the rest is cash. No stress gate (S3's job). The target
changes at the first assessment of each New York month; the backtest assesses month ends.

Research only: S4 makes no live signal yet; its backtests withhold performance (OD-7).
"""

import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from autotrading.domain.rotation import SnapshotInput, TrendCondition, TrendReading

STRATEGY = "S4"  # Medium-term Momentum
HUNDRED = Decimal(100)


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
