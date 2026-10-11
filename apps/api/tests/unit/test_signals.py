"""The buyback signal rule (M1.6, ADR-027 J1)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from autotrading.domain.signals import BUYBACK_FAMILY, BUYBACK_STRATEGY, buyback_signal

T = datetime(2026, 9, 30, 20, tzinfo=UTC)
ASSESSMENT = {
    "conditions": [
        {"condition_id": "a", "status": "pass"},
        {"condition_id": "b", "status": "pass"},
        {"condition_id": "c", "status": "fail"},
        {"condition_id": "d", "status": "unavailable"},
    ]
}


@pytest.mark.parametrize("state", ["active", "high_conviction"])
def test_a_qualifying_state_makes_one_long_paper_only_signal(state: str) -> None:
    signal = buyback_signal("id-1", state, Decimal("72.5"), ASSESSMENT, "0.2.0", T, T)
    assert signal is not None
    assert (signal.family_id, signal.strategy_id, signal.direction) == (
        BUYBACK_FAMILY,
        BUYBACK_STRATEGY,
        "long",
    )
    assert (signal.generated_at, signal.valid_from, signal.system_time) == (T, T, T)
    assert signal.observation_ids == [{"table": "buyback_state_assignments", "id": "id-1"}]
    assert (signal.score, signal.rule_version) == (Decimal("72.5"), "0.2.0")
    assert (signal.source_quality, signal.evidence_independence) == (1, 2)  # two passed
    assert signal.execution_eligibility == "paper_only"
    assert signal.backfilled is False


@pytest.mark.parametrize("state", ["none", "watch"])
def test_other_states_make_none(state: str) -> None:
    assert buyback_signal("id-1", state, Decimal(50), ASSESSMENT, "0.2.0", T, T) is None


def test_a_backfilled_assignment_makes_a_backfilled_signal() -> None:
    later = datetime(2026, 10, 11, tzinfo=UTC)
    signal = buyback_signal("id-1", "active", None, {"conditions": []}, "0.2.0", T, later)
    assert signal is not None
    assert (signal.backfilled, signal.generated_at, signal.system_time) == (True, T, later)
    assert (signal.score, signal.evidence_independence) == (None, 0)
