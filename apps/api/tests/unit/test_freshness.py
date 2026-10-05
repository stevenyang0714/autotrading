from datetime import UTC, datetime, timedelta

from autotrading.domain.freshness import freshness_status

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
SLA = 3600


def status(**overrides: object) -> object:
    fields: dict[str, object] = {
        "now": NOW,
        "enabled": True,
        "sla_seconds": SLA,
        "last_success_at": NOW - timedelta(minutes=10),
        "last_attempt_failed": False,
    }
    fields.update(overrides)
    return freshness_status(**fields)  # type: ignore[arg-type]


def test_recent_success_is_fresh() -> None:
    assert status() == "fresh"


def test_exactly_at_sla_is_still_fresh() -> None:
    assert status(last_success_at=NOW - timedelta(seconds=SLA)) == "fresh"


def test_flips_to_stale_when_sla_is_exceeded() -> None:
    # Acceptance (M0.3): time-mocked SLA breach.
    assert status(last_success_at=NOW - timedelta(seconds=SLA + 1)) == "stale"


def test_never_succeeded_is_stale() -> None:
    assert status(last_success_at=None) == "stale"


def test_latest_failure_is_failing_even_within_sla() -> None:
    assert status(last_attempt_failed=True) == "failing"


def test_disabled_source_is_not_judged() -> None:
    assert status(enabled=False, last_attempt_failed=True) is None
