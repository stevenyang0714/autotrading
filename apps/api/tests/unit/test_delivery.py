"""Alert delivery rules (M3.0b, ADR-037): which alerts are pushed, quiet hours, the message."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from autotrading.domain.delivery import (
    DeliveryRulesFile,
    StoredAlert,
    message,
    not_pushed,
)
from autotrading.settings import get_settings

FILE = DeliveryRulesFile.model_validate(
    yaml.safe_load(Path(get_settings().resolved_config_dir() / "delivery_rules.yaml").read_text())
)
RULES = FILE.active()
# A released version never changes (ADR-037): a new rule_version is the only way to edit one.
PINNED = {"0.1.0": "7b6a95934e7c41dad84ef2bd9988eff7bbf90b9cd3e8af3d15d9d0b17738149a"}
NOW = datetime(2026, 10, 20, 3, 20, tzinfo=UTC)  # 11:20 Singapore time


def alert(**changes: object) -> StoredAlert:
    base: dict[str, object] = {
        "id": "a-1",
        "rule_version": "0.6.0",
        "kind": "regime",
        "level": 2,
        "previous_level": 1,
        "title": "Market stress rose to HIGH (was ELEVATED)",
        "known_at": NOW - timedelta(minutes=5),
        "backfilled": False,
        "evidence": [{"table": "regime_assessments", "id": "r-1", "label": "VIX above 30"}],
    }
    base.update(changes)
    return StoredAlert(**base)  # type: ignore[arg-type]


def test_every_released_rule_set_is_pinned() -> None:
    assert {r.rule_version: r.rule_set().content_sha256() for r in FILE.rule_sets} == PINNED
    assert (RULES.channel, RULES.alert_rule_version, RULES.max_per_run) == ("telegram", "0.6.0", 10)
    assert set(RULES.kinds) == {"regime", "level_change", "rotation", "momentum", "portfolio"}


def test_which_alerts_are_pushed() -> None:
    assert not_pushed(RULES, alert(), NOW) is None
    for kind in ("rotation", "momentum", "portfolio"):
        assert not_pushed(RULES, alert(kind=kind), NOW) is None
    assert not_pushed(RULES, alert(kind="event", level=0), NOW) == "event alerts are not pushed"
    assert not_pushed(RULES, alert(backfilled=True), NOW) == "backfilled"
    assert not_pushed(RULES, alert(rule_version="0.5.0"), NOW) == "alert rules 0.5.0, not 0.6.0"
    old = alert(known_at=NOW - timedelta(hours=49))
    assert not_pushed(RULES, old, NOW) == "older than 48 hours"


def test_company_levels_are_pushed_into_and_out_of_l3() -> None:
    up = alert(kind="level_change", level=3, previous_level=2)
    down = alert(kind="level_change", level=2, previous_level=4)
    low = alert(kind="level_change", level=2, previous_level=1)
    assert not_pushed(RULES, up, NOW) is None
    assert not_pushed(RULES, down, NOW) is None
    assert not_pushed(RULES, low, NOW) == "below L3"


@pytest.mark.parametrize(
    ("hour", "minute", "quiet"),
    [(15, 0, True), (22, 59, True), (23, 0, False), (14, 59, False), (3, 20, False)],
)
def test_quiet_hours_span_midnight_singapore_time(hour: int, minute: int, quiet: bool) -> None:
    # 15:00 UTC is 23:00 SGT; 22:59 UTC is 06:59 SGT; 23:00 UTC is 07:00 SGT
    at = datetime(2026, 10, 20, hour, minute, tzinfo=UTC)
    assert RULES.quiet_hours.holds(at) is quiet


def test_the_message_is_plain_text_with_the_disclaimer_and_no_link() -> None:
    evidence = [{"table": "t", "id": str(i), "label": f"flag {i}"} for i in range(5)]
    text = message(RULES, alert(evidence=evidence))
    lines = text.split("\n")
    assert lines[0] == "[autotrading] Market stress rose to HIGH (was ELEVATED)"
    assert lines[1] == "Market stress · known 2026-10-20 11:15 +08 · alert rules 0.6.0"
    assert lines[2] == "Evidence: flag 0; flag 1; flag 2 (+2 more)"
    assert lines[-1] == "Rule output, unvalidated, not advice. Paper only."
    assert "http" not in text and "<" not in text
    long = message(RULES, alert(title="x" * 5000))
    assert len(long) <= 4000 and long.endswith("Paper only.")


def test_the_rules_file_needs_one_active_version() -> None:
    raw = yaml.safe_load(
        Path(get_settings().resolved_config_dir() / "delivery_rules.yaml").read_text()
    )
    raw["rule_sets"][0]["status"] = "retired"
    with pytest.raises(ValueError, match="exactly one rule set must be active"):
        DeliveryRulesFile.model_validate(raw)
