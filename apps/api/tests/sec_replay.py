"""Recorded SEC responses (tests/fixtures/sec) replayed through the real ingestion jobs.

Used by the integration tests, and by CI through tests/replay.py (`make replay-fixtures`), so
the instrument page has real data without network access or a SEC_USER_AGENT.
"""

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx2 as httpx

from autotrading.adapters.sec.client import SecClient
from autotrading.adapters.sec.company import SecCompanyJob
from autotrading.adapters.sec.refresh import create_company_runs
from autotrading.adapters.sec.tickers import SecTickersJob
from autotrading.ingestion.job import JobRegistry, Window, register_job
from autotrading.ingestion.runner import IngestionRunner

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
