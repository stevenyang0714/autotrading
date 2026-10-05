"""Dramatiq actors.

Worker entry point: `dramatiq autotrading.jobs.actors --processes 1 --threads 2`.
Importing this module loads settings (enforcing the live-trading guard, ADR-008)
and configures the broker before any actor is declared.
"""

import dramatiq

from autotrading.infra.heartbeat import write_heartbeat
from autotrading.infra.redis_client import make_redis
from autotrading.jobs.broker import configure_broker
from autotrading.settings import get_settings

_settings = get_settings()
broker = configure_broker(_settings)
_redis = make_redis(_settings)


@dramatiq.actor(queue_name="system", max_retries=0, time_limit=10_000, broker=broker)
def heartbeat() -> None:
    """Record that the worker is consuming jobs. Enqueued by the scheduler."""
    write_heartbeat(_redis, "worker")
