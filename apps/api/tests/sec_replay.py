"""Recorded SEC responses (tests/fixtures/sec) replayed through the real ingestion jobs.

Used by the integration tests, and by CI through tests/replay.py (`make replay-fixtures`), so
the instrument page has real data without network access or a SEC_USER_AGENT.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx2 as httpx

from autotrading.adapters.sec.client import SecClient
from autotrading.adapters.sec.company import SecCompanyJob
from autotrading.adapters.sec.earnings import SecEarningsReleaseJob
from autotrading.adapters.sec.eight_k import SecEightKJob
from autotrading.adapters.sec.filing_xbrl import SecFilingXbrlJob
from autotrading.adapters.sec.refresh import (
    create_company_runs,
    create_earnings_run,
    create_eight_k_run,
    create_filing_xbrl_run,
)
from autotrading.adapters.sec.tickers import SecTickersJob
from autotrading.ingestion.job import JobRegistry, Window, register_job
from autotrading.ingestion.runner import IngestionRunner

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sec"
MANIFEST: dict[str, Any] = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
USER_AGENT = "Test Runner test@example.com"
# Universe tickers whose filings and facts are recorded (XOM includes its predecessor; META is
# the issuer whose share counts are tagged per class only, ADR-021).
RECORDED_TICKERS = ("AAPL", "XOM", "META")

# Filings whose own XBRL instance is recorded (ADR-021).
RECORDED_INSTANCES = frozenset(MANIFEST.get("instances", []))
# 8-Ks whose documents are recorded (M1.4a, ADR-025).
RECORDED_EIGHT_KS = frozenset(MANIFEST.get("eight_ks", []))

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
    # Recorded 2026-10-05, before SEC's acceptance-time bug (adapters/sec/acceptance.py).
    trust_json_acceptance = True

    def client(self) -> SecClient:
        return recorded_client()


class RecordedFilingXbrl(SecFilingXbrlJob):
    def client(self) -> SecClient:
        return recorded_client()


class RecordedEightK(SecEightKJob):
    def client(self) -> SecClient:
        return recorded_client()


class RecordedEarningsRelease(SecEarningsReleaseJob):
    def client(self) -> SecClient:
        return recorded_client()


class VerifyingCompany(SecCompanyJob):
    """Replays like production: new filings are timed from their EDGAR headers."""

    def client(self) -> SecClient:
        return recorded_client()


def recorded_registry() -> JobRegistry:
    registry: JobRegistry = {}
    register_job(RecordedTickers, registry)
    register_job(RecordedCompany, registry)
    register_job(RecordedFilingXbrl, registry)
    register_job(RecordedEightK, registry)
    register_job(RecordedEarningsRelease, registry)
    return registry


def replay(
    runner: IngestionRunner,
    window: Window,
    predecessors: dict[str, list[dict[str, Any]]],
    tickers: tuple[str, ...] = RECORDED_TICKERS,
    before_instances: Callable[[], list[UUID]] | None = None,
) -> list[UUID]:
    """The tickers run, one company run per CIK, then the filing XBRL runs of the recorded
    instances, and the 8-K and earnings-release runs of the recorded 8-Ks, as a refresh would;
    returns run ids."""
    tickers_run = runner.create_run(
        SecTickersJob.name, {"tickers": list(tickers), "predecessors": predecessors}, window
    )
    runner.execute(tickers_run)
    company_runs = create_company_runs(runner, tickers_run)
    for run_id in company_runs:
        runner.execute(run_id)
    # e.g. the splits, which production fetches before the SEC refresh
    between = before_instances() if before_instances else []
    instance_runs = [
        run
        for company_run in company_runs
        if (run := create_filing_xbrl_run(runner, company_run, only=RECORDED_INSTANCES))
    ]
    for run_id in instance_runs:
        runner.execute(run_id)
    eight_k_runs = [
        run
        for company_run in company_runs
        for create in (create_eight_k_run, create_earnings_run)
        if (run := create(runner, company_run, only=RECORDED_EIGHT_KS))
    ]
    for run_id in eight_k_runs:
        runner.execute(run_id)
    return [tickers_run, *company_runs, *between, *instance_runs, *eight_k_runs]
