"""Recorded SEC responses (tests/fixtures/sec) replayed through the real ingestion jobs.

Used by the integration tests, and by CI (`make sec-replay`) to load the recordings into the
stack database so the instrument page has real data without network access or a
SEC_USER_AGENT:

    cd apps/api && uv run python -m tests.sec_replay
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx2 as httpx
from sqlalchemy.orm import sessionmaker

from autotrading.adapters.sec.client import SecClient
from autotrading.adapters.sec.company import SecCompanyJob
from autotrading.adapters.sec.refresh import (
    create_company_runs,
    refresh_window,
    universe_predecessors,
)
from autotrading.adapters.sec.tickers import SecTickersJob
from autotrading.infra.db import make_engine
from autotrading.infra.object_store import ensure_bucket, make_s3_client
from autotrading.infra.redis_client import make_redis
from autotrading.ingestion.job import JobRegistry, Window, register_job
from autotrading.ingestion.rate_limit import TokenBucketLimiter
from autotrading.ingestion.raw_store import RawPayloadStore
from autotrading.ingestion.runner import IngestionRunner
from autotrading.settings import get_settings

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sec"
MANIFEST: dict[str, Any] = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
USER_AGENT = "Test Runner test@example.com"
# Universe tickers whose filings and facts are recorded (XOM includes its predecessor).
RECORDED_TICKERS = ("AAPL", "XOM")

# Mutations of the recorded data for single tests, keyed by URL.
OVERRIDES: dict[str, bytes] = {}


def serve(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    assert request.headers["User-Agent"] == USER_AGENT
    if url in OVERRIDES:
        return httpx.Response(200, content=OVERRIDES[url])
    name = MANIFEST["files"].get(url)
    if name is None:
        return httpx.Response(404)
    return httpx.Response(200, content=(FIXTURES / name).read_bytes())


def recorded_client() -> SecClient:
    return SecClient(USER_AGENT, transport=httpx.MockTransport(serve))


class RecordedTickers(SecTickersJob):
    def client(self) -> SecClient:
        return recorded_client()


class RecordedCompany(SecCompanyJob):
    def client(self) -> SecClient:
        return recorded_client()


def recorded_registry() -> JobRegistry:
    registry: JobRegistry = {}
    register_job(RecordedTickers, registry)
    register_job(RecordedCompany, registry)
    return registry


def replay(
    runner: IngestionRunner,
    window: Window,
    predecessors: dict[str, list[dict[str, Any]]],
    tickers: tuple[str, ...] = RECORDED_TICKERS,
) -> list[UUID]:
    """The tickers run, then one company run per CIK, as a refresh would; returns run ids."""
    tickers_run = runner.create_run(
        SecTickersJob.name, {"tickers": list(tickers), "predecessors": predecessors}, window
    )
    runner.execute(tickers_run)
    company_runs = create_company_runs(runner, tickers_run)
    for run_id in company_runs:
        runner.execute(run_id)
    return [tickers_run, *company_runs]


def main() -> None:
    settings = get_settings()
    s3 = make_s3_client(settings)
    ensure_bucket(s3, settings.s3_bucket)
    runner = IngestionRunner(
        sessionmaker(make_engine(settings)),
        RawPayloadStore(s3, settings.s3_bucket),
        TokenBucketLimiter(make_redis(settings)),
        recorded_registry(),
    )
    run_ids = replay(
        runner,
        refresh_window(datetime.now(UTC), manual=True),
        universe_predecessors(settings.resolved_config_dir()),
    )
    print(f"replayed {len(run_ids)} recorded SEC runs ({', '.join(RECORDED_TICKERS)})")


if __name__ == "__main__":
    main()
