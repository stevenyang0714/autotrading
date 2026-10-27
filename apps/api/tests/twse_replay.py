"""Recorded TWSE OpenAPI files (tests/fixtures/twse) replayed through the real `twse.daily` job,
one recorded day per run, in order (M3.7). Each day's files are served by URL; a file not
recorded that day is a 404, as a broken source would be.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar
from uuid import UUID

import httpx2 as httpx

from autotrading.adapters.twse.client import TwseClient
from autotrading.adapters.twse.daily import TwseDailyJob
from autotrading.ingestion.job import JobRegistry, Window, register_job
from autotrading.ingestion.runner import IngestionRunner

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "twse"
MANIFEST: dict[str, Any] = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
DAYS: dict[str, dict[str, Any]] = {d["label"]: d for d in MANIFEST["days"]}


def server(label: str) -> Callable[[httpx.Request], httpx.Response]:
    files: dict[str, str] = DAYS[label]["files"]

    def serve(request: httpx.Request) -> httpx.Response:
        name = files.get(str(request.url))
        if name is None:
            return httpx.Response(404, json={"error": "not recorded"})
        return httpx.Response(
            200,
            content=(FIXTURES / name).read_bytes(),
            headers={"content-type": "application/json"},
        )

    return serve


def payload(label: str, name: str) -> Any:
    """One recorded file of a day, parsed (e.g. payload('d1', 'STOCK_DAY_ALL'))."""
    return json.loads((FIXTURES / f"{label}_{name}.json").read_text(encoding="utf-8"))


class RecordedTwseDaily(TwseDailyJob):
    def client(self) -> TwseClient:
        return TwseClient(
            transport=httpx.MockTransport(server(str(self.params["fixture_day"]))),
            sleep=lambda _: None,
        )


class FixtureTwseDaily(RecordedTwseDaily):
    """Recorded data labelled as such (the DEMO DATA banner, ADR-006)."""

    feed_status: ClassVar[str] = "fixture"
    data_mode: ClassVar[str] = "fixture"


def register_recorded(registry: JobRegistry, *, fixture: bool = False) -> JobRegistry:
    register_job(FixtureTwseDaily if fixture else RecordedTwseDaily, registry)
    return registry


def replay(runner: IngestionRunner, window: Window, days: list[str] | None = None) -> list[UUID]:
    """One `twse.daily` run per recorded day (all of them by default), in order."""
    run_ids = []
    for label in days or list(DAYS):
        run_id = runner.create_run(
            TwseDailyJob.name, {"slot": "replay", "fixture_day": label}, window
        )
        runner.execute(run_id)
        run_ids.append(run_id)
    return run_ids
