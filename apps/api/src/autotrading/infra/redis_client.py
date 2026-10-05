"""Redis client factory and health probe. Redis is cache/queue only, never a source of truth."""

from redis import Redis

from autotrading.infra.probes import PROBE_TIMEOUT_SECONDS, ProbeResult, run_probe
from autotrading.settings import Settings


def make_redis(settings: Settings) -> Redis:
    return Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=PROBE_TIMEOUT_SECONDS,
        socket_timeout=PROBE_TIMEOUT_SECONDS,
        decode_responses=True,
    )


def probe_redis(client: Redis) -> ProbeResult:
    def check() -> None:
        client.ping()

    return run_probe(check)
