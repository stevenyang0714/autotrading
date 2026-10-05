"""Shared result type and timing helper for dependency health probes."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

ProbeStatus = Literal["ok", "down", "stale"]

PROBE_TIMEOUT_SECONDS = 2


@dataclass(frozen=True)
class ProbeResult:
    status: ProbeStatus
    latency_ms: float
    detail: str | None = None


def run_probe(check: Callable[[], str | None]) -> ProbeResult:
    """Run `check` and time it. `check` returns an optional detail or raises.

    On failure only the exception class name is reported: driver error messages
    can contain hostnames, usernames or credentials.
    """
    started = time.perf_counter()
    try:
        detail = check()
    except Exception as exc:
        return ProbeResult("down", _elapsed_ms(started), type(exc).__name__)
    return ProbeResult("ok", _elapsed_ms(started), detail)


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
