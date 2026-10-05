"""Per-source token bucket in Redis (M0.3).

The Lua script runs atomically and uses the Redis clock, so concurrent workers share one bucket
per source. Missing tokens are not borrowed: the caller sleeps for the reported wait and retries.
"""

import time
from decimal import Decimal

from redis import Redis

_TOKEN_BUCKET = """
local rate = tonumber(ARGV[1])
local burst = tonumber(ARGV[2])
local requested = tonumber(ARGV[3])
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
local state = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(state[1]) or burst
local ts = tonumber(state[2]) or now
tokens = math.min(burst, tokens + math.max(0, now - ts) * rate)
local wait = 0
if tokens >= requested then
    tokens = tokens - requested
else
    wait = (requested - tokens) / rate
end
redis.call('HSET', KEYS[1], 'tokens', tostring(tokens), 'ts', tostring(now))
redis.call('EXPIRE', KEYS[1], math.ceil(burst / rate) + 60)
return tostring(wait)
"""


class RateLimitTimeoutError(TimeoutError):
    """A token did not become available within the caller's timeout."""


class TokenBucketLimiter:
    def __init__(self, redis: Redis, *, prefix: str = "ratelimit") -> None:
        self._redis = redis
        self._prefix = prefix
        self._script = redis.register_script(_TOKEN_BUCKET)

    def try_acquire(self, source_id: str, *, rate: Decimal | float, burst: int) -> float:
        """Take one token if available. Returns 0.0 on success, else seconds to wait."""
        wait = self._script(keys=[f"{self._prefix}:{source_id}"], args=[str(rate), burst, 1])
        return float(wait)

    def acquire(
        self, source_id: str, *, rate: Decimal | float, burst: int, timeout: float = 60.0
    ) -> None:
        deadline = time.monotonic() + timeout
        while True:
            wait = self.try_acquire(source_id, rate=rate, burst=burst)
            if wait <= 0:
                return
            if time.monotonic() + wait > deadline:
                raise RateLimitTimeoutError(f"rate limit for {source_id} not available in time")
            time.sleep(wait)
