"""Alpaca client safety (ADR-004, ADR-017): market data host only, paper keys only, keys in
headers and never in URLs or logs; retries and paging."""

import json
import logging
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx2 as httpx
import pytest

from autotrading.adapters.alpaca.bars import AlpacaDailyBarsJob
from autotrading.adapters.alpaca.client import (
    DATA_HOST,
    AlpacaClient,
    AlpacaConfigError,
    AlpacaRequestError,
)
from autotrading.ingestion.job import FetchContext, Window

KEY, SECRET = "PKUNITTEST00000000000", "unit-test-secret-value"


def no_wait() -> None:
    pass


def client_with(handler: httpx.MockTransport, sleeps: list[float] | None = None) -> AlpacaClient:
    recorded = sleeps if sleeps is not None else []
    return AlpacaClient(KEY, SECRET, transport=handler, sleep=recorded.append)


@pytest.mark.parametrize(
    "path",
    ["/v2/orders", "/v2/account", "/v2/positions", "/v1/trading/accounts", "/v2/stocksx"],
)
def test_only_market_data_endpoints_are_reachable(path: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    client = client_with(httpx.MockTransport(handler))
    with pytest.raises(AlpacaRequestError, match="not a market data endpoint"):
        client.get(path, {}, no_wait)
    assert requests == []


def test_requests_go_to_the_data_host_with_keys_in_headers() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    payload = client_with(httpx.MockTransport(handler)).get(
        "/v2/stocks/snapshots", {"symbols": "SPY", "feed": "iex"}, no_wait
    )
    (request,) = seen
    assert request.url.host == DATA_HOST
    assert request.url.host not in {"api.alpaca.markets", "paper-api.alpaca.markets"}
    assert request.headers["APCA-API-KEY-ID"] == KEY
    assert request.headers["APCA-API-SECRET-KEY"] == SECRET
    assert KEY not in str(request.url) and SECRET not in str(request.url)
    assert payload.source_url == (
        "https://data.alpaca.markets/v2/stocks/snapshots?symbols=SPY&feed=iex"
    )


@pytest.mark.parametrize(
    ("key", "secret", "message"),
    [
        ("AKLIVEKEY000000000000", SECRET, "live-account key"),
        ("", SECRET, "not set"),
        (KEY, " ", "not set"),
    ],
)
def test_live_or_missing_keys_are_refused(key: str, secret: str, message: str) -> None:
    with pytest.raises(AlpacaConfigError, match=message) as error:
        AlpacaClient(key, secret)
    assert SECRET not in str(error.value) and (not key or key not in str(error.value))


def test_retries_rate_limits_without_logging_keys(caplog: pytest.LogCaptureFixture) -> None:
    responses = iter([httpx.Response(429, headers={"retry-after": "3"}), httpx.Response(200)])
    sleeps: list[float] = []
    client = client_with(httpx.MockTransport(lambda _: next(responses)), sleeps)
    with caplog.at_level(logging.DEBUG):
        client.get("/v2/stocks/bars", {"symbols": "SPY"}, no_wait)
    assert sleeps == [3.0]
    assert "429" in caplog.text
    assert KEY not in caplog.text and SECRET not in caplog.text


def test_gives_up_on_a_refusal() -> None:
    client = client_with(httpx.MockTransport(lambda _: httpx.Response(403)))
    with pytest.raises(AlpacaRequestError, match="HTTP 403 after 1 attempt"):
        client.get("/v2/stocks/bars", {"symbols": "SPY"}, no_wait)


def test_daily_bars_follow_next_page_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        query = parse_qs(urlparse(str(request.url)).query)
        if request.url.path == "/v1/corporate-actions":
            return httpx.Response(200, json={"corporate_actions": {}, "next_page_token": None})
        token = query.get("page_token", [None])[0]
        bar = {"t": "2026-10-05T04:00:00Z", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}
        if token is None:
            return httpx.Response(200, json={"bars": {"SPY": [bar]}, "next_page_token": "p2"})
        assert token == "p2"
        return httpx.Response(200, json={"bars": {"SPY": [bar]}, "next_page_token": None})

    class Job(AlpacaDailyBarsJob):
        def client(self) -> AlpacaClient:
            return client_with(httpx.MockTransport(handler))

    job = Job({"symbols": ["SPY"], "etfs": ["SPY"], "start": "2026-10-01"}, Window())
    payloads = job.fetch(FetchContext(run_id=uuid4(), acquire=no_wait))
    urls = [p.source_url for p in payloads]
    # Corporate actions, then two raw pages and two split-adjusted pages.
    assert len(urls) == 5 and "corporate-actions" in urls[0]
    assert ["page_token=p2" in url for url in urls[1:]] == [False, True, False, True]
    assert all(json.loads(p.content) for p in payloads)
