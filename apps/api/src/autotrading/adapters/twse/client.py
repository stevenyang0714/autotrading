"""HTTP access to the TWSE OpenAPI (M3.7, ADR-039 TW1).

Only the six licensed OpenAPI files are reachable: the client refuses any other path, and
never the website's dated queries (www.twse.com.tw/rwd), whose terms of use (Art. 6) forbid
automated download without TWSE's consent. Every endpoint serves the latest session only and
takes no parameter. Free, no key; data under the Open Government Data License Taiwan 1.0,
which requires attribution (shown wherever the data is). Every request takes a token from the
per-source rate limiter first (config/sources.yaml).
"""

import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Self

import httpx2 as httpx

from autotrading.ingestion.job import FetchedPayload

logger = logging.getLogger(__name__)

SOURCE_ID = "twse_openapi"
API_BASE = "https://openapi.twse.com.tw/v1"
DAY = "/exchangeReport/STOCK_DAY_ALL"  # 上市個股日成交資訊
VALUATION = "/exchangeReport/BWIBBU_d"  # 上市個股日本益比、殖利率及股價淨值比
MARGIN = "/exchangeReport/MI_MARGN"  # 集中市場融資融券餘額
EX_RIGHTS = "/exchangeReport/TWT48U_ALL"  # 上市股票除權除息預告表
COMPANIES = "/opendata/t187ap03_L"  # 上市公司基本資料
HOLIDAYS = "/holidaySchedule/holidaySchedule"  # 有價證券集中交易市場開（休）市日期
ALLOWED_PATHS = frozenset({DAY, VALUATION, MARGIN, EX_RIGHTS, COMPANIES, HOLIDAYS})
DATASET_NAMES = {
    DAY: "上市個股日成交資訊",
    VALUATION: "上市個股日本益比、殖利率及股價淨值比",
    MARGIN: "集中市場融資融券餘額",
    EX_RIGHTS: "上市股票除權除息預告表",
    COMPANIES: "上市公司基本資料",
    HOLIDAYS: "有價證券集中交易市場開（休）市日期",
}
USER_AGENT = "autotrading-research/0.1 (personal, non-commercial research)"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 4
BASE_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 60.0
TIMEOUT_SECONDS = 60.0


class TwseRequestError(RuntimeError):
    """TWSE kept refusing or failing a request after the client's own retries."""


def public_url(path: str) -> str:
    if path not in ALLOWED_PATHS:
        raise ValueError(f"{path} is not one of the licensed TWSE OpenAPI files")
    return f"{API_BASE}{path}"


class TwseClient:
    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = httpx.Client(
            timeout=TIMEOUT_SECONDS,
            follow_redirects=False,
            transport=transport,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        self._sleep = sleep

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get(self, path: str, acquire: Callable[[], None]) -> FetchedPayload:
        url = public_url(path)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            acquire()
            try:
                response = self._client.get(url)
            except httpx.TransportError as exc:
                if attempt == MAX_ATTEMPTS:
                    raise TwseRequestError(f"GET {url} failed: {type(exc).__name__}") from None
                self._sleep(self._backoff(attempt, None))
                continue
            if response.status_code == 200:
                try:
                    json.loads(response.content)
                except ValueError:
                    raise TwseRequestError(f"GET {url} did not return JSON") from None
                return FetchedPayload(
                    content=response.content,
                    content_type=response.headers.get("content-type", "application/json"),
                    source_url=url,
                    fetched_at=datetime.now(UTC),
                )
            if response.status_code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS:
                raise TwseRequestError(
                    f"GET {url} returned HTTP {response.status_code} after {attempt} attempt(s)"
                )
            delay = self._backoff(attempt, response.headers.get("retry-after"))
            logger.warning(
                "TWSE returned HTTP %s for %s; retrying in %.1fs", response.status_code, url, delay
            )
            self._sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _backoff(attempt: int, retry_after: str | None) -> float:
        if retry_after is not None and retry_after.isdigit():
            return min(float(retry_after), MAX_BACKOFF_SECONDS)
        return min(BASE_BACKOFF_SECONDS * 2.0 ** (attempt - 1), MAX_BACKOFF_SECONDS)
