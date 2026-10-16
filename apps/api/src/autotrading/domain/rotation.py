"""ETF rotation research, strategy S3 (M2.4, ADR-032; 02 §13, §15, §18). Pure; no I/O.

Each ETF of the rotation universe is judged against its own history only (no ranking across
ETFs: P2-3, KI-1). Its trend is up when every trend measure of its factor snapshot is above its
threshold (12-1 momentum and the close against its 200-session average, rules 0.1.0). The
market's stress state (the regime engine) gates what may be held: each state allows some
sleeves (risk, defensive) and says whether high-beta ETFs may be held. The selected ETFs are
held in equal weights, rounded down; the rest is cash.

The target changes at the first assessment of each New York month (`month_start`), and at once
when the stress state rises into a defensive state (`defensive_switch`). Otherwise the previous
target is carried. When the regime is unavailable or stale the assessment is `unavailable`:
it has no target, and the next assessment carries from the last one that had a target.

A target makes two paper signals per held ETF, both long, for strategy S3: family 5 (its trend
is up) and family 1 (the stress state allows it). Signals are made when a target is set, never
when it is carried. Research only: nothing here places or prepares an order.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from autotrading.domain.convergence import AlertIn
from autotrading.domain.signals import SOURCE_QUALITY, SignalIn
from autotrading.domain.splits import NEW_YORK

StressState = Literal["normal", "elevated", "high", "crisis"]
SleeveName = Literal["risk", "defensive"]
Reason = Literal["month_start", "defensive_switch", "carried", "unavailable"]
TREND_FAMILY = 5  # Price / Trend / Factor (domain/registries.py)
REGIME_FAMILY = 1  # Macro Regime
STRATEGY = "S3"  # Macro Regime / ETF Rotation
HUNDRED = Decimal(100)
STRESS_ORDER: dict[str, int] = {"normal": 0, "elevated": 1, "high": 2, "crisis": 3}


# ---------- rules ----------


class _Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Sleeves(_Rule):
    risk: list[str]
    defensive: list[str]

    def of(self, symbol: str) -> SleeveName:
        return "risk" if symbol in self.risk else "defensive"

    def universe(self) -> list[str]:
        return [*self.risk, *self.defensive]


class TrendCondition(_Rule):
    measure: str
    above: Decimal


class HighBeta(_Rule):
    measure: str
    at_least: Decimal
    benchmark: str
    benchmark_beta: Decimal


class Gate(_Rule):
    sleeves: list[SleeveName]
    high_beta: bool


class Gates(_Rule):
    normal: Gate
    elevated: Gate
    high: Gate
    crisis: Gate

    def of(self, stress: StressState) -> Gate:
        gate: Gate = getattr(self, stress)
        return gate


class RotationRuleSet(_Rule):
    """One released rule version: immutable, like the regime rule sets (ADR-029)."""

    rule_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    released: date
    note: str
    regime_rule_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    factor_definition_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    sleeves: Sleeves
    trend: Annotated[list[TrendCondition], Field(min_length=1)]
    high_beta: HighBeta
    gates: Gates
    defensive_switch: list[StressState]
    weight_quantum_pct: Annotated[Decimal, Field(gt=0)]
    regime_stale_after_days: Annotated[int, Field(gt=0)]
    factor_stale_after_days: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def _distinct(self) -> "RotationRuleSet":
        universe = self.sleeves.universe()
        if len(universe) != len(set(universe)):
            raise ValueError("an ETF is in more than one sleeve")
        return self

    def content(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"status"}, exclude_defaults=True)

    def content_sha256(self) -> str:
        canonical = json.dumps(self.content(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class RotationRuleSetEntry(RotationRuleSet):
    status: Literal["active", "retired"]

    def rule_set(self) -> RotationRuleSet:
        return RotationRuleSet.model_validate(self.content())


class RotationRulesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    rule_sets: list[RotationRuleSetEntry]

    @model_validator(mode="after")
    def _one_active(self) -> "RotationRulesFile":
        versions = [r.rule_version for r in self.rule_sets]
        if len(versions) != len(set(versions)):
            raise ValueError("duplicate rule_version")
        if sum(r.status == "active" for r in self.rule_sets) != 1:
            raise ValueError("exactly one rule set must be active")
        return self

    def active(self) -> RotationRuleSet:
        return next(r.rule_set() for r in self.rule_sets if r.status == "active")


# ---------- inputs ----------


@dataclass(frozen=True)
class RegimeInput:
    """A stored regime assessment known at T (regime_assessments)."""

    id: str
    known_at: datetime
    rule_version: str
    stress: StressState | None
    quadrant: str | None
    stress_detail: str


@dataclass(frozen=True)
class MeasureInput:
    value: Decimal | None
    detail: str


@dataclass(frozen=True)
class SnapshotInput:
    """A stored factor snapshot of one ETF known at T (factor_snapshots)."""

    id: str
    symbol: str
    known_at: datetime
    definition_version: str
    last_close: date | None
    feed_status: str | None
    measures: Mapping[str, MeasureInput]


@dataclass(frozen=True)
class PreviousTarget:
    """The latest stored assessment before T that had a target."""

    id: str
    known_at: datetime
    stress: StressState | None
    target: Mapping[str, Decimal]  # symbol -> weight in percent
    set_at: datetime  # when that target was set (its rebalance)


# ---------- results ----------


class Reading(BaseModel):
    measure: str
    value: Decimal | None
    threshold: Decimal
    status: Literal["pass", "fail", "unavailable"]
    detail: str


class EtfReading(BaseModel):
    """One ETF as read at T: its trend, beta and whether the stress state allows it."""

    symbol: str
    sleeve: SleeveName
    snapshot_id: str | None
    snapshot_known_at: datetime | None
    last_close: date | None
    feed_status: str | None
    trend: list[Reading]
    trend_up: bool
    beta: Decimal | None
    high_beta: bool
    allowed: bool  # by the stress state at T
    eligible: bool  # trend up and allowed: would be selected if the target were set at T
    detail: str


class Holding(BaseModel):
    symbol: str
    sleeve: SleeveName
    weight_pct: Decimal


class Rotation(BaseModel):
    """Everything a rotation assessment stores: recomputing it gives the same document."""

    rule_version: str
    known_at: datetime
    regime_id: str | None
    regime_known_at: datetime | None
    stress: StressState | None
    quadrant: str | None  # context only (KI-7); the rules do not read it
    stress_detail: str
    gate: Gate | None
    readings: list[EtfReading]
    rebalance: bool
    reason: Reason
    detail: str
    previous_id: str | None
    set_at: datetime | None  # when the target in force was set
    target: list[Holding] | None  # None when unavailable
    cash_pct: Decimal | None

    def weights(self) -> dict[str, Decimal]:
        return {h.symbol: h.weight_pct for h in self.target or []}

    def risk_pct(self) -> Decimal:
        return sum((h.weight_pct for h in self.target or [] if h.sleeve == "risk"), Decimal(0))


# ---------- assessment ----------


def _ny_month(at: datetime) -> tuple[int, int]:
    local = at.astimezone(NEW_YORK)
    return local.year, local.month


def _trend(rules: RotationRuleSet, snapshot: SnapshotInput) -> list[Reading]:
    out: list[Reading] = []
    for condition in rules.trend:
        measure = snapshot.measures.get(condition.measure)
        if measure is None or measure.value is None:
            out.append(
                Reading(
                    measure=condition.measure,
                    value=None,
                    threshold=condition.above,
                    status="unavailable",
                    detail=measure.detail if measure else "not in the factor snapshot",
                )
            )
            continue
        passed = measure.value > condition.above
        out.append(
            Reading(
                measure=condition.measure,
                value=measure.value,
                threshold=condition.above,
                status="pass" if passed else "fail",
                detail=f"{measure.value} {'>' if passed else '<='} {condition.above}",
            )
        )
    return out


def read_etf(
    rules: RotationRuleSet, at: datetime, symbol: str, snapshot: SnapshotInput | None, gate: Gate
) -> EtfReading:
    sleeve = rules.sleeves.of(symbol)
    sleeve_allowed = sleeve in gate.sleeves
    stale = snapshot is not None and at - snapshot.known_at > timedelta(
        days=rules.factor_stale_after_days
    )
    if snapshot is None or stale:
        detail = (
            "no factor snapshot known at T"
            if snapshot is None
            else f"the factor snapshot of {snapshot.known_at.date()} is older than "
            f"{rules.factor_stale_after_days} days"
        )
        return EtfReading(
            symbol=symbol,
            sleeve=sleeve,
            snapshot_id=snapshot.id if snapshot else None,
            snapshot_known_at=snapshot.known_at if snapshot else None,
            last_close=snapshot.last_close if snapshot else None,
            feed_status=snapshot.feed_status if snapshot else None,
            trend=[],
            trend_up=False,
            beta=None,
            high_beta=False,
            allowed=False,
            eligible=False,
            detail=detail,
        )
    trend = _trend(rules, snapshot)
    trend_up = all(r.status == "pass" for r in trend)
    if symbol == rules.high_beta.benchmark:
        beta: Decimal | None = rules.high_beta.benchmark_beta
    else:
        found = snapshot.measures.get(rules.high_beta.measure)
        beta = found.value if found else None
    # an unknown beta counts as high: the stricter reading when a gate excludes high beta
    high_beta = beta is None or beta >= rules.high_beta.at_least
    allowed = sleeve_allowed and (gate.high_beta or not high_beta)
    if not sleeve_allowed:
        why = f"the {sleeve} sleeve is not allowed"
    elif not allowed:
        why = "high beta is not allowed" if beta is not None else "beta unavailable (high beta)"
    elif not trend_up:
        failed = [r.measure for r in trend if r.status != "pass"]
        why = "trend not up: " + ", ".join(failed)
    else:
        why = "trend up and allowed"
    return EtfReading(
        symbol=symbol,
        sleeve=sleeve,
        snapshot_id=snapshot.id,
        snapshot_known_at=snapshot.known_at,
        last_close=snapshot.last_close,
        feed_status=snapshot.feed_status,
        trend=trend,
        trend_up=trend_up,
        beta=beta,
        high_beta=high_beta,
        allowed=allowed,
        eligible=trend_up and allowed,
        detail=why,
    )


def equal_weights(rules: RotationRuleSet, readings: Sequence[EtfReading]) -> list[Holding]:
    chosen = [r for r in readings if r.eligible]
    if not chosen:
        return []
    weight = (HUNDRED / len(chosen)).quantize(rules.weight_quantum_pct, rounding=ROUND_DOWN)
    return [Holding(symbol=r.symbol, sleeve=r.sleeve, weight_pct=weight) for r in chosen]


def _holdings(rules: RotationRuleSet, weights: Mapping[str, Decimal]) -> list[Holding]:
    return [
        Holding(symbol=s, sleeve=rules.sleeves.of(s), weight_pct=weights[s])
        for s in rules.sleeves.universe()
        if s in weights
    ]


def _cash(target: Sequence[Holding]) -> Decimal:
    return HUNDRED - sum((h.weight_pct for h in target), Decimal(0))


def assess(
    rules: RotationRuleSet,
    at: datetime,
    regime: RegimeInput | None,
    snapshots: Mapping[str, SnapshotInput],
    previous: PreviousTarget | None,
) -> Rotation:
    """The rotation at T from the regime and factor snapshots known then, and the previous
    target (ADR-032 Q1, Q2)."""
    stale = regime is not None and at - regime.known_at > timedelta(
        days=rules.regime_stale_after_days
    )
    if regime is None or stale or regime.stress is None:
        detail = (
            "no regime assessment known at T"
            if regime is None
            else f"the regime assessment of {regime.known_at.date()} is older than "
            f"{rules.regime_stale_after_days} days"
            if stale
            else f"stress state unavailable: {regime.stress_detail}"
        )
        return Rotation(
            rule_version=rules.rule_version,
            known_at=at,
            regime_id=regime.id if regime else None,
            regime_known_at=regime.known_at if regime else None,
            stress=None,
            quadrant=regime.quadrant if regime else None,
            stress_detail=regime.stress_detail if regime else "",
            gate=None,
            readings=[],
            rebalance=False,
            reason="unavailable",
            detail=detail,
            previous_id=previous.id if previous else None,
            set_at=None,
            target=None,
            cash_pct=None,
        )
    gate = rules.gates.of(regime.stress)
    readings = [read_etf(rules, at, s, snapshots.get(s), gate) for s in rules.sleeves.universe()]
    switch = (
        previous is not None
        and regime.stress in rules.defensive_switch
        and (previous.stress is None or previous.stress not in rules.defensive_switch)
    )
    if previous is None or _ny_month(at) != _ny_month(previous.known_at):
        reason: Reason = "month_start"
    elif switch:
        reason = "defensive_switch"
    else:
        reason = "carried"
    if reason == "carried":
        assert previous is not None
        target = _holdings(rules, previous.target)
        set_at: datetime = previous.set_at
        detail = f"target of {previous.set_at.astimezone(NEW_YORK).date()} carried"
    else:
        target = equal_weights(rules, readings)
        set_at = at
        held = ", ".join(h.symbol for h in target) or "cash only"
        why = (
            "first assessment of the month"
            if reason == "month_start"
            else f"stress rose to {regime.stress.upper()}"
        )
        detail = f"{why}: {held}"
    return Rotation(
        rule_version=rules.rule_version,
        known_at=at,
        regime_id=regime.id,
        regime_known_at=regime.known_at,
        stress=regime.stress,
        quadrant=regime.quadrant,
        stress_detail=regime.stress_detail,
        gate=gate,
        readings=readings,
        rebalance=reason != "carried",
        reason=reason,
        detail=detail,
        previous_id=previous.id if previous else None,
        set_at=set_at,
        target=target,
        cash_pct=_cash(target),
    )


# ---------- signals and alerts ----------


def signals(
    rotation: Rotation, assessment_id: str, system_time: datetime
) -> list[tuple[str, SignalIn]]:
    """(symbol, signal) for each ETF of a newly set target: family 5 (trend up, scored by its
    first trend measure) and family 1 (allowed by the stress state). None when carried."""
    if not rotation.rebalance or not rotation.target:
        return []

    def make(
        family: int, score: Decimal | None, observation: dict[str, str], independence: int
    ) -> SignalIn:
        return SignalIn(
            family_id=family,
            strategy_id=STRATEGY,
            rule_version=rotation.rule_version,
            score=score,
            direction="long",
            generated_at=rotation.known_at,
            valid_from=rotation.known_at,
            system_time=system_time,
            observation_ids=[{"table": "rotation_assessments", "id": assessment_id}, observation],
            source_quality=SOURCE_QUALITY,
            evidence_independence=independence,
            execution_eligibility="paper_only",
            backfilled=system_time > rotation.known_at,
        )

    by_symbol = {r.symbol: r for r in rotation.readings}
    out: list[tuple[str, SignalIn]] = []
    for holding in rotation.target:
        reading = by_symbol[holding.symbol]
        trend = make(
            TREND_FAMILY,
            reading.trend[0].value if reading.trend else None,
            {"table": "factor_snapshots", "id": reading.snapshot_id or ""},
            sum(r.status == "pass" for r in reading.trend),
        )
        regime = make(
            REGIME_FAMILY, None, {"table": "regime_assessments", "id": rotation.regime_id or ""}, 1
        )
        out += [(holding.symbol, trend), (holding.symbol, regime)]
    return out


def _held(weights: Mapping[str, Decimal]) -> str:
    return ", ".join(weights) or "cash only"


def rotation_alert(
    rotation: Rotation, previous: Mapping[str, Decimal] | None, assessment_id: str
) -> AlertIn | None:
    """An alert when a newly set target differs from the previous one (ADR-032 Q2): `down`
    when the risk sleeve's weight fell, `up` otherwise."""
    if not rotation.rebalance or previous is None or rotation.weights() == dict(previous):
        return None
    sleeve = {r.symbol: r.sleeve for r in rotation.readings}
    was = sum((w for s, w in previous.items() if sleeve.get(s) == "risk"), Decimal(0))
    down = rotation.risk_pct() < was
    why = "defensive switch" if rotation.reason == "defensive_switch" else "monthly target"
    title = f"S3 rotation ({why}): now {_held(rotation.weights())} (was {_held(previous)})"
    return AlertIn(
        kind="rotation",
        level=0,
        previous_level=0,
        direction="down" if down else "up",
        title=title,
        source_key=f"rotation:{assessment_id}",
        known_at=rotation.known_at,
        evidence=[
            {
                "table": "rotation_assessments",
                "id": assessment_id,
                "label": f"Stress {(rotation.stress or 'unavailable').upper()}: {rotation.detail}",
            }
        ],
    )
