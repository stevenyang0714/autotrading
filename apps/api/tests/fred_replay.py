"""Recorded FRED responses (tests/fixtures/fred) replayed through the real `fred.series` job.

Requests are matched on their URL without the API key, as the recorder stored them
(adapters/fred/client.py `public_url`). The replay key is a dummy of the right shape.
"""

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse
from uuid import UUID

import httpx2 as httpx

from autotrading.adapters.fred.client import FredClient
from autotrading.adapters.fred.series import FredSeriesJob
from autotrading.ingestion.job import JobRegistry, Window, register_job
from autotrading.ingestion.runner import IngestionRunner

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "fred"
MANIFEST: dict[str, Any] = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
DUMMY_KEY = "0123456789abcdef0123456789abcdef"
# Series -> first recorded observation date (the job's observation_start when recorded).
RECORDED_SERIES: dict[str, str] = MANIFEST["observation_start"]


def serve(request: httpx.Request) -> httpx.Response:
    url = urlparse(str(request.url))
    query = [(k, v) for k, v in parse_qsl(url.query) if k != "api_key"]
    public = f"{url.scheme}://{url.netloc}{url.path}?{urlencode(query)}"
    name = MANIFEST["files"].get(public)
    if name is None:
        return httpx.Response(404, json={"error_code": 404, "error_message": "not recorded"})
    return httpx.Response(200, content=(FIXTURES / name).read_bytes())


class RecordedFredSeries(FredSeriesJob):
    def client(self) -> FredClient:
        return FredClient(DUMMY_KEY, transport=httpx.MockTransport(serve))


def register_recorded(registry: JobRegistry) -> JobRegistry:
    register_job(RecordedFredSeries, registry)
    return registry


def replay(runner: IngestionRunner, window: Window) -> list[UUID]:
    """One `fred.series` run per recorded series, with the recorded observation start."""
    run_ids = [
        runner.create_run(
            FredSeriesJob.name, {"series_id": series_id, "observation_start": start}, window
        )
        for series_id, start in RECORDED_SERIES.items()
    ]
    for run_id in run_ids:
        runner.execute(run_id)
    return run_ids
