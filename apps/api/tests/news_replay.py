"""Recorded news responses (tests/fixtures/news) replayed through the real jobs.

Requests are matched on their URL, rebuilt the way the client stores it (adapters/news/
client.py `public_url`). The recorded feeds are the stripped feeds the jobs store; stripping
them again changes nothing.

Two labels: `Replayed*` jobs store items as the real jobs do (data_mode live), for the
integration tests; `Fixture*` jobs label them `fixture` (ADR-006), for CI and the e2e tests.
"""

import json
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import parse_qsl, urlencode, urlsplit
from uuid import UUID

import httpx2 as httpx

from autotrading.adapters.news.client import NewsClient
from autotrading.adapters.news.config import feeds
from autotrading.adapters.news.gdelt import GdeltJob
from autotrading.adapters.news.rss import RssJob, job_for
from autotrading.ingestion.job import JobRegistry, Window, register_job
from autotrading.ingestion.runner import IngestionRunner

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "news"
MANIFEST: dict[str, Any] = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
SYNDICATION_CASE: dict[str, Any] = MANIFEST["syndication_case"]


def serve(request: httpx.Request) -> httpx.Response:
    parts = urlsplit(str(request.url))
    query = urlencode(parse_qsl(parts.query))
    public = f"{parts.scheme}://{parts.netloc}{parts.path}" + (f"?{query}" if query else "")
    name = MANIFEST["files"].get(public)
    if name is None:
        return httpx.Response(404, text="not recorded")
    return httpx.Response(200, content=(FIXTURES / name).read_bytes())


def recorded_client() -> NewsClient:
    hosts = {urlsplit(url).hostname or "" for url in MANIFEST["files"]}
    return NewsClient(hosts, transport=httpx.MockTransport(serve), sec_user_agent="Test t@e.st")


class ReplayedGdelt(GdeltJob):
    def client(self) -> NewsClient:
        return recorded_client()


class FixtureGdelt(ReplayedGdelt):
    data_mode: ClassVar[str] = "fixture"


class ReplayedRss(RssJob):
    def client(self) -> NewsClient:
        return recorded_client()


class FixtureRss(ReplayedRss):
    data_mode: ClassVar[str] = "fixture"


def register_recorded(registry: JobRegistry, *, fixture: bool = True) -> JobRegistry:
    register_job(FixtureGdelt if fixture else ReplayedGdelt, registry)
    for feed in feeds().values():
        register_job(job_for(feed, FixtureRss if fixture else ReplayedRss), registry)
    return registry


def replay(runner: IngestionRunner, window: Window) -> list[UUID]:
    """Every recorded run: GDELT over the recorded window, then each feed once."""
    run_ids = [runner.create_run(run["job"], run["params"], window) for run in MANIFEST["runs"]]
    for run_id in run_ids:
        runner.execute(run_id)
    return run_ids
