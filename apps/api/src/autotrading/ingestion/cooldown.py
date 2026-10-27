"""A pause a throttled source asks for (M3.7b, ADR-040 TW16; KI-30).

When a provider throttles (FinMind's 402/403, GDELT's repeated 429), retrying only holds a
worker thread and earns a longer block. The client starts a cooldown instead; every later
request of that source, in any process, checks it first and sends nothing until it ends. Shared
through Redis; tests use the in-process one.
"""

import time
from datetime import UTC, datetime
from typing import Any, Protocol, Self

from autotrading.infra.redis_client import make_redis
from autotrading.settings import get_settings


class Cooldown(Protocol):
    def active(self) -> bool: ...

    def start(self, seconds: int) -> None: ...


class RedisCooldown:
    """A cooldown every process sees (the worker's retries included)."""

    def __init__(self, redis: Any, key: str) -> None:
        self._redis = redis
        self._key = key

    @classmethod
    def from_settings(cls, key: str) -> Self:
        return cls(make_redis(get_settings()), key)

    def active(self) -> bool:
        return bool(self._redis.exists(self._key))

    def start(self, seconds: int) -> None:
        self._redis.setex(self._key, seconds, datetime.now(UTC).isoformat())


class MemoryCooldown:
    """A cooldown inside one process (tests, the recorders)."""

    def __init__(self) -> None:
        self.until = 0.0

    def active(self) -> bool:
        return time.monotonic() < self.until

    def start(self, seconds: int) -> None:
        self.until = time.monotonic() + seconds
