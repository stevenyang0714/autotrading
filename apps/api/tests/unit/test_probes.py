import pytest

from autotrading.infra.heartbeat import (
    HEARTBEAT_TTL_SECONDS,
    heartbeat_key,
    probe_heartbeat,
    write_heartbeat,
)
from autotrading.infra.probes import run_probe


class FakeStore:
    def __init__(self, fail: bool = False) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.fail = fail

    def set(self, name: str, value: str, ex: int) -> object:
        self.values[name] = value
        self.ttls[name] = ex
        return True

    def get(self, name: str) -> object:
        if self.fail:
            raise ConnectionError("redis://user:secret@redis:6379 refused")
        return self.values.get(name)


def test_run_probe_ok_returns_detail() -> None:
    result = run_probe(lambda: "fine")
    assert result.status == "ok"
    assert result.detail == "fine"
    assert result.latency_ms >= 0


def test_run_probe_failure_reports_only_exception_class() -> None:
    def check() -> None:
        raise RuntimeError("connection to postgresql://app:secret@db failed")

    result = run_probe(check)
    assert result.status == "down"
    assert result.detail == "RuntimeError"


def test_heartbeat_written_with_ttl_is_ok() -> None:
    store = FakeStore()
    write_heartbeat(store, "worker")
    assert store.ttls[heartbeat_key("worker")] == HEARTBEAT_TTL_SECONDS
    assert probe_heartbeat(store, "worker").status == "ok"


def test_missing_heartbeat_is_stale_not_down() -> None:
    result = probe_heartbeat(FakeStore(), "scheduler")
    assert result.status == "stale"


@pytest.mark.parametrize("component", ["worker", "scheduler"])
def test_heartbeat_store_error_is_down_without_leaking(component: str) -> None:
    result = probe_heartbeat(FakeStore(fail=True), component)  # type: ignore[arg-type]
    assert result.status == "down"
    assert result.detail == "ConnectionError"
