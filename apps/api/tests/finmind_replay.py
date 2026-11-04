"""Recorded FinMind responses (tests/fixtures/finmind, and the longer price histories of
tests/fixtures/finmind_prices for the Taiwan screens, M3.11) replayed through the real
`finmind.flows` and `finmind.history` jobs (M3.7b). Requests are matched on their full URL, as
the recorders stored them; a URL not recorded is a 404, as a broken source would be.
"""

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import httpx2 as httpx

from autotrading.adapters.finmind.client import (
    DIVIDENDS,
    INSTITUTIONAL,
    MARGIN,
    PER,
    PRICE,
    SHAREHOLDING,
    FinMindClient,
    MemoryCooldown,
)
from autotrading.adapters.finmind.daily import FinMindFlowsJob
from autotrading.adapters.finmind.history import FinMindHistoryJob
from autotrading.ingestion.job import JobRegistry, Window, register_job
from autotrading.ingestion.runner import IngestionRunner

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "finmind"
PRICES = Path(__file__).resolve().parent / "fixtures" / "finmind_prices"
MANIFEST: dict[str, Any] = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
PRICE_MANIFEST: dict[str, Any] = json.loads((PRICES / "manifest.json").read_text(encoding="utf-8"))
FILES: dict[str, Path] = {
    **{url: FIXTURES / name for url, name in MANIFEST["files"].items()},
    **{url: PRICES / name for url, name in PRICE_MANIFEST["files"].items()},
}
WINDOW = (date(2026, 10, 1), date(2026, 10, 22))  # the recorded range of the daily datasets
HISTORY = (date(2016, 1, 1), date(2026, 10, 26))  # the recorded range of the dividend results
CODES = ("2330", "2317")
DIVIDEND_CODES = ("2330", "2881", "2317")


def serve(request: httpx.Request) -> httpx.Response:
    path = FILES.get(str(request.url))
    if path is None:
        return httpx.Response(404, json={"msg": "not recorded", "status": 404})
    return httpx.Response(
        200, content=path.read_bytes(), headers={"content-type": "application/json"}
    )


def payload(code: str, dataset: str) -> Any:
    """One recorded response, parsed (the whole envelope)."""
    return json.loads((FIXTURES / f"{code}_{dataset}.json").read_text(encoding="utf-8"))


def price_history(code: str) -> tuple[Any, dict[str, object]]:
    """A longer recorded TaiwanStockPrice response (the whole envelope) and the history run's
    params that fetch it (tests/fixtures/finmind_prices)."""
    url, name = next(
        (url, name) for url, name in PRICE_MANIFEST["files"].items() if name.startswith(code)
    )
    query = parse_qs(urlparse(url).query)
    params: dict[str, object] = {
        "code": code,
        "dataset": PRICE,
        "start": query["start_date"][0],
        "end": query["end_date"][0],
    }
    return json.loads((PRICES / name).read_text(encoding="utf-8")), params


PRICE_CODES = ("2330", "2881", "2454", "3711", "2303", "2408")


def recorded_client(
    serve_with: Callable[[httpx.Request], httpx.Response] = serve,
) -> FinMindClient:
    return FinMindClient(
        cooldown=MemoryCooldown(), transport=httpx.MockTransport(serve_with), sleep=lambda _: None
    )


class RecordedFinMindFlows(FinMindFlowsJob):
    def client(self) -> FinMindClient:
        return recorded_client()


class RecordedFinMindHistory(FinMindHistoryJob):
    def client(self) -> FinMindClient:
        return recorded_client()


class FixtureFinMindFlows(RecordedFinMindFlows):
    """Recorded data labelled as such (the DEMO DATA banner, ADR-006)."""

    feed_status: ClassVar[str] = "fixture"
    data_mode: ClassVar[str] = "fixture"


class FixtureFinMindHistory(RecordedFinMindHistory):
    feed_status: ClassVar[str] = "fixture"
    data_mode: ClassVar[str] = "fixture"


def register_recorded(registry: JobRegistry, *, fixture: bool = False) -> JobRegistry:
    register_job(FixtureFinMindFlows if fixture else RecordedFinMindFlows, registry)
    register_job(FixtureFinMindHistory if fixture else RecordedFinMindHistory, registry)
    return registry


def history_params(code: str, dataset: str) -> dict[str, object]:
    start, end = HISTORY if dataset == DIVIDENDS else WINDOW
    return {"code": code, "dataset": dataset, "start": start.isoformat(), "end": end.isoformat()}


def replay_history(runner: IngestionRunner, window: Window) -> list[UUID]:
    """The recorded history: five datasets for 2330 and 2317 over the window, and the dividend
    results of 2330, 2881 and 2317 since 2016."""
    run_ids = []
    for code in CODES:
        for dataset in (PRICE, MARGIN, PER, INSTITUTIONAL, SHAREHOLDING):
            run_ids.append(
                runner.create_run(FinMindHistoryJob.name, history_params(code, dataset), window)
            )
    for code in DIVIDEND_CODES:
        run_ids.append(
            runner.create_run(FinMindHistoryJob.name, history_params(code, DIVIDENDS), window)
        )
    for run_id in run_ids:
        runner.execute(run_id)
    return run_ids


def replay_prices(runner: IngestionRunner, window: Window) -> list[UUID]:
    """The longer price histories of tests/fixtures/finmind_prices, after the TWSE sessions (a
    TWSE session is compared, never overwritten)."""
    run_ids = [
        runner.create_run(FinMindHistoryJob.name, price_history(code)[1], window)
        for code in PRICE_CODES
    ]
    for run_id in run_ids:
        runner.execute(run_id)
    return run_ids


def replay_flows(
    runner: IngestionRunner, window: Window, *, price_codes: list[str] | None = None
) -> UUID:
    """One flows run over the recorded window for 2330 and 2317."""
    params: dict[str, object] = {
        "codes": list(CODES),
        "start": WINDOW[0].isoformat(),
        "end": WINDOW[1].isoformat(),
    }
    if price_codes:
        params["price_codes"] = price_codes
    run_id = runner.create_run(FinMindFlowsJob.name, params, window)
    runner.execute(run_id)
    return run_id
