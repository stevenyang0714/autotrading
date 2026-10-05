"""Liveness heartbeats for background components, stored as expiring Redis keys.

The scheduler writes its own heartbeat and enqueues the `heartbeat` actor; the worker
writes its heartbeat when it runs that actor. A fresh worker key therefore proves the
whole scheduler -> queue -> worker path works.
"""

from datetime import UTC, datetime
from typing import Literal, Protocol

from autotrading.infra.probes import ProbeResult, run_probe

Component = Literal["worker", "scheduler"]

HEARTBEAT_INTERVAL_SECONDS = 30
HEARTBEAT_TTL_SECONDS = 90


class HeartbeatStore(Protocol):
    def set(self, name: str, value: str, ex: int) -> object: ...

    def get(self, name: str) -> object: ...


def heartbeat_key(component: Component) -> str:
    return f"heartbeat:{component}"


def write_heartbeat(store: HeartbeatStore, component: Component) -> None:
    store.set(heartbeat_key(component), datetime.now(UTC).isoformat(), ex=HEARTBEAT_TTL_SECONDS)


def probe_heartbeat(store: HeartbeatStore, component: Component) -> ProbeResult:
    def check() -> str | None:
        value = store.get(heartbeat_key(component))
        return None if value is None else f"last beat {value}"

    result = run_probe(check)
    if result.status == "ok" and result.detail is None:
        # A missing heartbeat means the component is late, not that a core dependency is down.
        return ProbeResult("stale", result.latency_ms, "no heartbeat within TTL")
    return result
