"""Recorded Alpaca responses (tests/fixtures/alpaca) replayed through the real jobs.

Requests are matched on their URL, rebuilt the way the client stores it (adapters/alpaca/
client.py `public_url`); keys are headers, so a dummy paper-shaped key is enough.

Two labels: `Replayed*` jobs store what the real jobs store (live_single_venue quotes,
end_of_day bars) for the integration tests of the feed status rules; `Fixture*` jobs label
everything `fixture` (ADR-006), for CI and the e2e tests (`make replay-fixtures`).
"""

import json
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import parse_qsl, urlencode, urlparse
from uuid import UUID

import httpx2 as httpx

from autotrading.adapters.alpaca.bars import AlpacaDailyBarsJob
from autotrading.adapters.alpaca.client import BASE_URL, AlpacaClient
from autotrading.adapters.alpaca.dividends import AlpacaDividendsJob
from autotrading.adapters.alpaca.snapshots import AlpacaSnapshotsJob
from autotrading.adapters.alpaca.splits import AlpacaSplitsJob
from autotrading.domain.prices import FeedStatus
from autotrading.ingestion.job import JobRegistry, Window, register_job
from autotrading.ingestion.runner import IngestionRunner

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "alpaca"
MANIFEST: dict[str, Any] = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
DUMMY_KEY_ID, DUMMY_SECRET = "PKTEST0000000000000000", "test-secret"


def recorded_params(job: str, index: int = 0) -> dict[str, Any]:
    """Params of the `index`-th recorded run of `job` (see record.py)."""
    params: dict[str, Any] = [run["params"] for run in MANIFEST["runs"] if run["job"] == job][index]
    return params


def serve(request: httpx.Request) -> httpx.Response:
    url = urlparse(str(request.url))
    public = f"{BASE_URL}{url.path}?{urlencode(parse_qsl(url.query))}"
    name = MANIFEST["files"].get(public)
    if name is None:
        return httpx.Response(404, json={"message": "not recorded"})
    return httpx.Response(
        200, content=(FIXTURES / name).read_bytes(), headers={"content-type": "application/json"}
    )


def recorded_client() -> AlpacaClient:
    return AlpacaClient(DUMMY_KEY_ID, DUMMY_SECRET, transport=httpx.MockTransport(serve))


class ReplayedSnapshots(AlpacaSnapshotsJob):
    def client(self) -> AlpacaClient:
        return recorded_client()


class ReplayedDailyBars(AlpacaDailyBarsJob):
    def client(self) -> AlpacaClient:
        return recorded_client()


class ReplayedSplits(AlpacaSplitsJob):
    def client(self) -> AlpacaClient:
        return recorded_client()


class ReplayedDividends(AlpacaDividendsJob):
    def client(self) -> AlpacaClient:
        return recorded_client()


class FixtureSnapshots(ReplayedSnapshots):
    feed_status: ClassVar[FeedStatus] = "fixture"


class FixtureDailyBars(ReplayedDailyBars):
    feed_status: ClassVar[FeedStatus] = "fixture"


def register_recorded(registry: JobRegistry, *, fixture: bool = True) -> JobRegistry:
    if fixture:
        register_job(FixtureSnapshots, registry)
        register_job(FixtureDailyBars, registry)
    else:
        register_job(ReplayedSnapshots, registry)
        register_job(ReplayedDailyBars, registry)
    register_job(ReplayedSplits, registry)  # splits and dividends have no feed status
    register_job(ReplayedDividends, registry)
    return registry


def replay(runner: IngestionRunner, window: Window) -> list[UUID]:
    """Every recorded run (snapshots, one year of bars, the NVDA split window, splits,
    dividends, two earlier years of NVDA and SPY bars), in order."""
    run_ids = [runner.create_run(run["job"], run["params"], window) for run in MANIFEST["runs"]]
    for run_id in run_ids:
        runner.execute(run_id)
    return run_ids


def replay_splits(runner: IngestionRunner, window: Window) -> list[UUID]:
    """The recorded `alpaca.splits` run alone: run before SEC's filing XBRL runs, as in
    production (splits at 06:30 SGT, SEC at 10:00), so reconciliations see the splits."""
    run_id = runner.create_run("alpaca.splits", recorded_params("alpaca.splits"), window)
    runner.execute(run_id)
    return [run_id]
