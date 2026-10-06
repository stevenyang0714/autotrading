"""Dramatiq actors.

Worker entry point: `dramatiq autotrading.jobs.actors --processes 1 --threads 2`.
Importing this module loads settings (enforcing the live-trading guard, ADR-008)
and configures the broker before any actor is declared.
"""

import logging
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from uuid import UUID

import dramatiq
from sqlalchemy.orm import sessionmaker

from autotrading import adapters  # noqa: F401  (adapters register their ingestion jobs)
from autotrading.adapters.alpaca import refresh as alpaca_refresh
from autotrading.adapters.fred import refresh as fred_refresh
from autotrading.adapters.news import refresh as news_refresh
from autotrading.adapters.sec import refresh as sec_refresh
from autotrading.infra.db import make_engine
from autotrading.infra.heartbeat import write_heartbeat
from autotrading.infra.object_store import make_s3_client
from autotrading.infra.redis_client import make_redis
from autotrading.ingestion.actors import INGESTION_QUEUE, declare_ingestion_actor
from autotrading.ingestion.rate_limit import TokenBucketLimiter
from autotrading.ingestion.raw_store import RawPayloadStore
from autotrading.ingestion.runner import IngestionRunner
from autotrading.ingestion.schedule import market_calendar
from autotrading.jobs.broker import WorkerHeartbeat, configure_broker
from autotrading.settings import get_settings

logger = logging.getLogger(__name__)

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


# ---------- SEC EDGAR refresh (M0.5) ----------


@dramatiq.actor(queue_name=INGESTION_QUEUE, max_retries=3, broker=broker)
def enqueue_sec_companies(message_data: dict[str, Any], result: str) -> None:
    """on_success callback of the `sec.tickers` run: fan out one run per company."""
    tickers_run = UUID(message_data["args"][0])
    run_ids = sec_refresh.create_company_runs(ingestion_runner(), tickers_run)
    for run_id in run_ids:
        run_ingestion.send_with_options(args=(str(run_id),), on_success=enqueue_sec_filing_xbrl)
    logger.info("SEC refresh: %d company runs queued after tickers run %s", len(run_ids), result)


@dramatiq.actor(queue_name=INGESTION_QUEUE, max_retries=3, broker=broker)
def enqueue_sec_filing_xbrl(message_data: dict[str, Any], result: str) -> None:
    """on_success callback of a `sec.company` run: read new filings' own XBRL (M1.1)."""
    company_run = UUID(message_data["args"][0])
    run_id = sec_refresh.create_filing_xbrl_run(ingestion_runner(), company_run)
    if run_id is not None:
        run_ingestion.send(str(run_id))
        logger.info("SEC refresh: filing XBRL run %s queued after %s", run_id, result)


def start_sec_refresh(*, manual: bool) -> UUID | None:
    """Queue a refresh: the tickers run first, the company runs once it succeeds."""
    run_id = sec_refresh.start_refresh(
        ingestion_runner(),
        now=datetime.now(UTC),
        manual=manual,
        config_dir=_settings.resolved_config_dir(),
    )
    if run_id is None:
        logger.info("SEC refresh skipped: source sec_edgar is not enabled")
        return None
    run_ingestion.send_with_options(args=(str(run_id),), on_success=enqueue_sec_companies)
    return run_id


# ---------- FRED / ALFRED refresh (M0.6) ----------


def start_fred_refresh(*, manual: bool) -> list[UUID]:
    """Queue one run per enabled macro series; empty when the source is not enabled."""
    run_ids = fred_refresh.start_refresh(ingestion_runner(), now=datetime.now(UTC), manual=manual)
    if not run_ids:
        logger.info("FRED refresh skipped: source fred is not enabled or no series is enabled")
    for run_id in run_ids:
        run_ingestion.send(str(run_id))
    return run_ids


# ---------- Alpaca market data (M0.7) ----------


def start_alpaca_snapshots(*, force: bool = False) -> UUID | None:
    """Queue this minute's snapshot run during US market hours (or now, when forced)."""
    run_id = alpaca_refresh.start_snapshots(
        ingestion_runner(),
        now=datetime.now(UTC),
        calendar=market_calendar(),
        config_dir=_settings.resolved_config_dir(),
        force=force,
    )
    if run_id is not None:
        run_ingestion.send(str(run_id))
    return run_id


def start_alpaca_daily_bars(*, manual: bool, backfill: bool = False) -> UUID | None:
    run_id = alpaca_refresh.start_daily_bars(
        ingestion_runner(),
        now=datetime.now(UTC),
        manual=manual,
        config_dir=_settings.resolved_config_dir(),
        backfill=backfill,
    )
    if run_id is None:
        logger.info("Alpaca bars skipped: alpaca_iex is not enabled or has no keys")
    else:
        run_ingestion.send(str(run_id))
    return run_id


# ---------- news (M0.8) ----------


def start_news_gdelt(*, manual: bool) -> UUID | None:
    """Queue this hour's GDELT run (or one now, when manual)."""
    run_id = news_refresh.start_gdelt(ingestion_runner(), now=datetime.now(UTC), manual=manual)
    if run_id is None:
        logger.info("GDELT skipped: the gdelt source is not enabled")
    else:
        run_ingestion.send(str(run_id))
    return run_id


def start_news_gdelt_backfill() -> list[UUID]:
    run_ids = news_refresh.start_gdelt_backfill(ingestion_runner(), now=datetime.now(UTC))
    for run_id in run_ids:
        run_ingestion.send(str(run_id))
    return run_ids


def start_news_feeds(*, manual: bool) -> list[UUID]:
    """Queue one run per enabled RSS / Atom feed."""
    run_ids = news_refresh.start_feeds(ingestion_runner(), now=datetime.now(UTC), manual=manual)
    for run_id in run_ids:
        run_ingestion.send(str(run_id))
    return run_ids
