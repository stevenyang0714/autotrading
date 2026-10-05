"""Dramatiq broker configuration (Redis broker, ADR-002)."""

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from autotrading.settings import Settings


def configure_broker(settings: Settings) -> RedisBroker:
    """Create the Redis broker and install it as Dramatiq's global broker.

    Must run before any actor is declared: actors bind to the broker at decoration time.
    """
    broker = RedisBroker(url=settings.redis_url)
    dramatiq.set_broker(broker)
    return broker
