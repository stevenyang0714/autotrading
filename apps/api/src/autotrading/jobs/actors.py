"""Dramatiq actors.

Worker entry point: `dramatiq autotrading.jobs.actors --processes 1 --threads 2`.
Importing this module loads settings (enforcing the live-trading guard, ADR-008)
and configures the broker before any actor is declared.
"""

from functools import lru_cache

import dramatiq
from sqlalchemy.orm import sessionmaker

from autotrading import adapters  # noqa: F401  (adapters register their ingestion jobs)
from autotrading.infra.db import make_engine
from autotrading.infra.heartbeat import write_heartbeat
from autotrading.infra.object_store import make_s3_client
from autotrading.infra.redis_client import make_redis
from autotrading.ingestion.actors import declare_ingestion_actor
from autotrading.ingestion.rate_limit import TokenBucketLimiter
from autotrading.ingestion.raw_store import RawPayloadStore
from autotrading.ingestion.runner import IngestionRunner
from autotrading.jobs.broker import WorkerHeartbeat, configure_broker
from autotrading.settings import get_settings

_settings = get_settings()
broker = configure_broker(_settings)
_redis = make_redis(_settings)
broker.add_middleware(WorkerHeartbeat(lambda: write_heartbeat(_redis, "worker")))


@dramatiq.actor(queue_name="system", max_retries=0, time_limit=10_000, broker=broker)
def heartbeat() -> None:
    """Prove the scheduler -> queue -> worker path. Enqueued by the scheduler."""
    write_heartbeat(_redis, "queue")


@lru_cache
def ingestion_runner() -> IngestionRunner:
    """Created on first use inside the worker, so importing this module stays cheap."""
    return IngestionRunner(
        sessionmaker(make_engine(_settings)),
        RawPayloadStore(make_s3_client(_settings), _settings.s3_bucket),
        TokenBucketLimiter(_redis),
    )


run_ingestion = declare_ingestion_actor(
    broker,
    ingestion_runner,
    max_retries=_settings.ingestion_max_retries,
    min_backoff_ms=_settings.ingestion_min_backoff_ms,
    max_backoff_ms=_settings.ingestion_max_backoff_ms,
)
