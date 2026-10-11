"""Signals (M1.6, ADR-027 J1; 02 §28, errata E1): a rule's output that something deserves a
look, recorded with the rule version and the observations behind it. Pure; no I/O.

Phase 1 has one source: a buyback state assignment (M1.4b) at ACTIVE or HIGH-CONVICTION makes
one long signal of family 2 (Corporate Actions & Capital Structure) for strategy S1 (Buyback +
Value + Quality). Earnings events make none: S2 needs a consensus estimate (OD-3).

Fields beyond the state:
- score: the assignment's Buyback Quality Score (unavailable stays empty);
- source_quality: 1, every input is an SEC filing or a consolidated close (tier 1);
- evidence_independence: how many rule conditions passed;
- execution_eligibility: paper_only. No risk check exists before Phase 2 (P1-4), and no signal
  ever places an order (ADR-008).
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

BUYBACK_FAMILY = 2  # Corporate Actions & Capital Structure (domain/registries.py)
BUYBACK_STRATEGY = "S1"  # Buyback + Value + Quality
QUALIFYING_STATES = frozenset({"active", "high_conviction"})
SOURCE_QUALITY = 1
Direction = Literal["long", "short", "neutral"]


@dataclass(frozen=True)
class SignalIn:
    family_id: int
    strategy_id: str | None
    rule_version: str
    score: Decimal | None
    direction: Direction
    generated_at: datetime
    valid_from: datetime
    system_time: datetime
    observation_ids: list[dict[str, str]]  # [{"table": ..., "id": ...}]
    source_quality: int
    evidence_independence: int
    execution_eligibility: Literal["paper_only"]
    backfilled: bool


def buyback_signal(
    assignment_id: str,
    state: str,
    score: Decimal | None,
    assessment: dict[str, Any],
    rule_version: str,
    known_at: datetime,
    system_time: datetime,
) -> SignalIn | None:
    """The signal of one stored buyback state assignment, if its state qualifies (J1)."""
    if state not in QUALIFYING_STATES:
        return None
    passed = sum(1 for c in assessment.get("conditions", []) if c.get("status") == "pass")
    return SignalIn(
        family_id=BUYBACK_FAMILY,
        strategy_id=BUYBACK_STRATEGY,
        rule_version=rule_version,
        score=score,
        direction="long",
        generated_at=known_at,
        valid_from=known_at,
        system_time=system_time,
        observation_ids=[{"table": "buyback_state_assignments", "id": assignment_id}],
        source_quality=SOURCE_QUALITY,
        evidence_independence=passed,
        execution_eligibility="paper_only",
        backfilled=system_time > known_at,
    )
