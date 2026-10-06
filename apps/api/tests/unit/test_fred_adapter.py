"""FRED adapter without network or database: key handling, retries, paging and parsing."""

import json
import logging
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx2 as httpx
import pytest

from autotrading.adapters.fred.client import (
    MAX_ATTEMPTS,
    FredClient,
    FredConfigError,
    FredRequestError,
    public_url,
)
from autotrading.adapters.fred.series import (
    FredSeriesJob,
    parse_last_updated,
    parse_value,
    payload_kind,
    realtime_windows,
)
from autotrading.domain.macro import period_end
from autotrading.ingestion.job import FetchContext, Window

KEY = "abcdef0123456789abcdef0123456789"  # shape of a FRED key; not a real one


def client_with(
    responses: list[httpx.Response],
) -> tuple[FredClient, list[httpx.Request], list[float]]:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return responses.pop(0)

    return (
        FredClient(KEY, transport=httpx.MockTransport(handler), sleep=sleeps.append),
        requests,
        sleeps,
    )


# ---------- key handling (ADR-015) ----------


@pytest.mark.parametrize("value", [None, "", "  "])
def test_missing_key_fails_fast(value: str | None) -> None:
    with pytest.raises(FredConfigError, match="FRED_API_KEY is not set"):
        FredClient(value or "")


def test_malformed_key_is_rejected_without_echoing_it() -> None:
    with pytest.raises(FredConfigError) as error:
        FredClient("not-a-key-MyPrivateValue")
    assert "MyPrivateValue" not in str(error.value)


def test_key_is_sent_but_never_stored_or_logged(caplog: pytest.LogCaptureFixture) -> None:
    client, requests, _ = client_with([httpx.Response(200, json={"seriess": []})])
    with caplog.at_level(logging.DEBUG):
        payload = client.get("series", {"series_id": "PAYEMS"}, lambda: None)
    assert parse_qs(urlparse(str(requests[0].url)).query)["api_key"] == [KEY]
    assert (
        payload.source_url
        == "https://api.stlouisfed.org/fred/series?series_id=PAYEMS&file_type=json"
    )
    assert KEY not in payload.source_url
    assert KEY not in caplog.text


def test_errors_name_the_public_url_and_hide_key_like_text() -> None:
    body = {"error_code": 400, "error_message": f"Bad Request. Key {KEY} is not registered."}
    client, _, _ = client_with([httpx.Response(400, json=body)])
    with pytest.raises(FredRequestError) as error:
        client.get("series", {"series_id": "PAYEMS"}, lambda: None)
    message = str(error.value)
    assert "HTTP 400" in message and "series_id=PAYEMS" in message
    assert KEY not in message and "***" in message
    assert error.value.__cause__ is None and error.value.__suppress_context__


def test_rate_limit_answers_are_retried_with_backoff() -> None:
    client, requests, sleeps = client_with(
        [httpx.Response(429), httpx.Response(503), httpx.Response(200, json={"ok": True})]
    )
    tokens: list[None] = []
    client.get("series", {"series_id": "PAYEMS"}, lambda: tokens.append(None))
    assert (len(requests), len(tokens), sleeps) == (3, 3, [2.0, 4.0])


def test_persistent_failure_gives_up_after_the_last_attempt() -> None:
    client, requests, _ = client_with([httpx.Response(500)] * MAX_ATTEMPTS)
    with pytest.raises(FredRequestError, match="HTTP 500"):
        client.get("series", {"series_id": "PAYEMS"}, lambda: None)
    assert len(requests) == MAX_ATTEMPTS


def test_public_url_has_no_key_parameter() -> None:
    assert "api_key" not in public_url("series/observations", {"series_id": "GDPC1"})


# ---------- parsing ----------


@pytest.mark.parametrize(
    ("start", "frequency", "end"),
    [
        (date(2026, 8, 1), "M", date(2026, 8, 31)),
        (date(2024, 2, 1), "M", date(2024, 2, 29)),
        (date(2026, 4, 1), "Q", date(2026, 6, 30)),
        (date(2026, 10, 5), "D", date(2026, 10, 5)),
        (date(2026, 10, 3), "W", date(2026, 10, 9)),
        (date(2025, 1, 1), "A", date(2025, 12, 31)),
        (date(2025, 7, 1), "SA", date(2025, 12, 31)),
    ],
)
def test_period_end_from_the_fred_period_start(start: date, frequency: Any, end: date) -> None:
    assert period_end(start, frequency) == end


def test_missing_values_and_timestamps() -> None:
    assert parse_value(".") is None
    assert parse_value("159526") == Decimal("159526")
    assert parse_last_updated("2026-09-11 07:38:03-05") == datetime(
        2026, 9, 11, 7, 38, 3, tzinfo=timezone(timedelta(hours=-5))
    )
    assert parse_last_updated(None) is None


# ---------- job fetch: paging ----------


def observations_page(count: int, offset: int, rows: int) -> dict[str, Any]:
    return {
        "count": count,
        "offset": offset,
        "limit": 100000,
        "observations": [
            {
                "realtime_start": "2026-09-05",
                "realtime_end": "9999-12-31",
                "date": "2026-08-01",
                "value": "1",
            }
        ]
        * rows,
    }


class PagedJob(FredSeriesJob):
    pages: list[httpx.Response]
    seen: list[httpx.Request]

    def client(self) -> FredClient:
        def handler(request: httpx.Request) -> httpx.Response:
            self.seen.append(request)
            return self.pages.pop(0)

        return FredClient(KEY, transport=httpx.MockTransport(handler))


def test_fetch_reads_vintages_then_pages_through_observations() -> None:
    job = PagedJob({"series_id": "payems"}, Window())
    job.seen = []
    job.pages = [
        httpx.Response(200, json={"seriess": [{"id": "PAYEMS"}]}),
        httpx.Response(200, json={"count": 2, "vintage_dates": ["2026-09-05", "2026-10-02"]}),
        httpx.Response(200, json=observations_page(3, 0, 2)),
        httpx.Response(200, json=observations_page(3, 2, 1)),
    ]
    payloads = job.fetch(FetchContext(run_id=uuid4(), acquire=lambda: None))
    assert [payload_kind(p.source_url) for p in payloads] == [
        "series",
        "vintagedates",
        "observations",
        "observations",
    ]
    offsets = [parse_qs(urlparse(str(r.url)).query).get("offset") for r in job.seen[2:]]
    assert offsets == [["0"], ["2"]]
    query = parse_qs(urlparse(str(job.seen[2].url)).query)
    assert (query["series_id"], query["realtime_start"], query["realtime_end"]) == (
        ["PAYEMS"],
        ["1776-07-04"],
        ["9999-12-31"],
    )
    assert all(KEY not in p.source_url for p in payloads)
    assert json.loads(payloads[3].content)["offset"] == 2
    assert all(p.fetched_at <= datetime.now(UTC) for p in payloads)


def test_many_vintages_are_read_in_windows_under_freds_limit() -> None:
    vintages = [f"v{i:04d}" for i in range(5)]
    assert realtime_windows(vintages, size=10) == [("1776-07-04", "9999-12-31")]
    assert realtime_windows(vintages, size=2) == [
        ("1776-07-04", "v0001"),
        ("v0002", "v0003"),
        ("v0004", "9999-12-31"),
    ]
