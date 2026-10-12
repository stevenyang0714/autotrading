"""Signal convergence levels and alerts (M1.7, ADR-028)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from autotrading.domain.convergence import (
    AlertRulesFile,
    BuybackReading,
    Condition,
    Event,
    assess,
    event_alert,
    in_window,
    level_alert,
    new_events,
)
from autotrading.settings import get_settings

RULES = AlertRulesFile.model_validate(
    yaml.safe_load(Path(get_settings().resolved_config_dir() / "alert_rules.yaml").read_text())
)
ACTIVE = RULES.active()
T = datetime(2026, 10, 9, 3, tzinfo=UTC)
# A released version never changes (ADR-028): a new rule_version is the only way to edit one.
PINNED = {"0.1.0": "9257f4512f7c5976dcbfd732adb95444a85b71ecb2983f63fe52560971163f7e"}


def buyback(state: str = "active", **statuses: str) -> BuybackReading:
    conditions = {
        "high_conviction.dcf_discount": "fail",
        "high_conviction.fcf_yield": "fail",
        "trade_ready.above_average": "fail",
        "trade_ready.relative_return": "fail",
    } | {k.replace("__", "."): v for k, v in statuses.items()}
    return BuybackReading(
        assignment_id="a1",
        state=state,
        known_at=T,
        rule_version="0.2.0",
        conditions={k: Condition(v, None) for k, v in conditions.items()},  # type: ignore[arg-type]
    )


def event(kind: str, days_ago: float, source: str, row: str = "r") -> Event:
    return Event(
        kind=kind,  # type: ignore[arg-type]
        table="filings",
        row_id=f"{row}-{source}",
        source=source,
        known_at=T - timedelta(days=days_ago),
        label=f"{kind} {source}",
    )


def test_the_active_rule_set_is_pinned() -> None:
    assert ACTIVE.rule_version == "0.1.0"
    assert ACTIVE.content_sha256() == PINNED["0.1.0"]


def test_nothing_in_the_window_is_no_level() -> None:
    result = assess(ACTIVE, T, buyback("none"), [event("periodic_report", 40, "x")])
    assert (result.level, [c.status for c in result.levels][:2]) == (None, ["fail", "fail"])


def test_one_event_is_information_and_a_reading_plus_an_event_is_watch() -> None:
    assert assess(ACTIVE, T, buyback("none"), [event("periodic_report", 3, "x")]).level == 0
    watch = assess(ACTIVE, T, buyback("watch"), [event("earnings_release", 3, "x")])
    assert (watch.level, watch.independent_families) == (1, [2, 4])
    # Two events but no reading: still L0.
    two = [event("periodic_report", 3, "x"), event("earnings_release", 5, "y")]
    assert assess(ACTIVE, T, buyback("none"), two).level == 0


def test_rows_of_one_filing_count_once() -> None:
    same = [event("earnings_release", 3, "acc-1"), event("buyback_statement", 3, "acc-1", "s")]
    assert [e.source for e in in_window(same, T, 30)] == ["acc-1"]
    assert assess(ACTIVE, T, buyback("none"), same).level == 0


def test_thesis_needs_executed_buybacks_and_valuation_support() -> None:
    no_value = assess(ACTIVE, T, buyback("active"), [])
    assert (no_value.level, no_value.levels[2].detail) == (0, "no valuation support")
    thesis = assess(ACTIVE, T, buyback("active", high_conviction__fcf_yield="pass"), [])
    assert (thesis.level, thesis.independent_families) == (2, [2, 3])
    watch_only = assess(ACTIVE, T, buyback("watch", high_conviction__dcf_discount="pass"), [])
    assert (watch_only.level, watch_only.levels[2].status) == (1, "fail")
    unknown = assess(
        ACTIVE,
        T,
        buyback(
            "active",
            high_conviction__dcf_discount="unavailable",
            high_conviction__fcf_yield="unavailable",
        ),
        [],
    )
    assert unknown.levels[2].status == "unavailable"


def test_trade_candidate_adds_market_confirmation_and_l4_is_unreachable() -> None:
    result = assess(
        ACTIVE,
        T,
        buyback(
            "high_conviction",
            high_conviction__dcf_discount="pass",
            trade_ready__relative_return="pass",
        ),
        [],
    )
    assert (result.level, result.independent_families) == (3, [2, 3, 5])
    assert (result.levels[4].status, result.levels[4].detail) == (
        "unavailable",
        "needs the Phase 2 risk check, liquidity, sizing and compliance (P1-4)",
    )


def test_level_changes_raise_alerts_above_information() -> None:
    thesis = assess(ACTIVE, T, buyback("active", high_conviction__fcf_yield="pass"), [])
    up = level_alert("AAPL", thesis, 1, "level:x")
    assert up is not None
    assert (up.title, up.level, up.direction, up.previous_level) == (
        "AAPL reached L2 Thesis",
        2,
        "up",
        1,
    )
    assert {e["label"] for e in up.evidence} == {"Buyback state ACTIVE", "Valuation support"}
    down = level_alert("AAPL", assess(ACTIVE, T, buyback("none"), []), 2, "level:y")
    assert down is not None and down.title == "AAPL fell to none from L2 Thesis"
    assert level_alert("AAPL", thesis, 2, "level:z") is None  # unchanged
    info = assess(ACTIVE, T, buyback("none"), [event("periodic_report", 1, "x")])
    assert level_alert("AAPL", info, None, "level:w") is None  # none -> L0: event alerts


def test_event_alerts_since_the_previous_assessment() -> None:
    events = [event("periodic_report", d, f"s{d}") for d in (1, 5, 40)]
    assert [e.source for e in new_events(events, T - timedelta(days=3), T, 30)] == ["s1"]
    assert [e.source for e in new_events(events, None, T, 30)] == ["s5", "s1"]
    alert = event_alert("AAPL", events[0])
    assert (alert.level, alert.kind, alert.source_key) == (0, "event", "event:filings:r-s1")


def test_the_rules_file_needs_one_active_version() -> None:
    raw = yaml.safe_load(
        Path(get_settings().resolved_config_dir() / "alert_rules.yaml").read_text()
    )
    raw["rule_sets"][0]["status"] = "retired"
    with pytest.raises(ValueError, match="exactly one rule set must be active"):
        AlertRulesFile.model_validate(raw)


def test_a_state_reading_and_its_own_state_change_are_one_item() -> None:
    change = Event(
        kind="buyback_state_change",
        table="buyback_state_assignments",
        row_id="a1",
        source="buyback_state_assignments:a1",
        known_at=T,
        label="Buyback state ACTIVE (was WATCH)",
    )
    result = assess(ACTIVE, T, buyback("active"), [change])
    assert [i.label for i in result.items] == ["Buyback state ACTIVE"]
    assert (result.level, result.levels[0].detail) == (0, "1 item")
