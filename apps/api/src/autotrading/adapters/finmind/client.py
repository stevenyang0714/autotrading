"""HTTP access to the FinMind data API (M3.7b, ADR-040 TW16, TW22).

FinMind is a tier 2 aggregator used under its free anonymous tier (300 requests an hour, no
account, no token): personal non-commercial use, attribution 資料來源：FinMind wherever its
data shows, no redistribution. The client reaches one endpoint and six datasets only.

Quota: a 402 (over the hourly cap) or a 403 ("ip banned", after many 4xx in a short window) is
never retried. It starts a 35-minute cooldown shared through Redis, and every later request in
this process or another checks the cooldown before connecting, so the ingestion actor's retries
burn no quota. 429 and 5xx retry with backoff, as the TWSE client does.
"""

import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Self
from urllib.parse import urlencode

import httpx2 as httpx

from autotrading.ingestion.cooldown import Cooldown, MemoryCooldown, RedisCooldown
from autotrading.ingestion.job import FetchedPayload

logger = logging.getLogger(__name__)

SOURCE_ID = "finmind"
API_BASE = "https://api.finmindtrade.com/api/v4/data"
PRICE = "TaiwanStockPrice"
MARGIN = "TaiwanStockMarginPurchaseShortSale"
PER = "TaiwanStockPER"
DIVIDENDS = "TaiwanStockDividendResult"
INSTITUTIONAL = "TaiwanStockInstitutionalInvestorsBuySell"
SHAREHOLDING = "TaiwanStockShareholding"
ALLOWED_DATASETS = frozenset({PRICE, MARGIN, PER, DIVIDENDS, INSTITUTIONAL, SHAREHOLDING})
DATASET_NAMES = {
    PRICE: "FinMind TaiwanStockPrice（個股日成交）",
    MARGIN: "FinMind TaiwanStockMarginPurchaseShortSale（融資融券）",
    PER: "FinMind TaiwanStockPER（本益比、殖利率、股價淨值比）",
    DIVIDENDS: "FinMind TaiwanStockDividendResult（除權除息結果）",
    INSTITUTIONAL: "FinMind TaiwanStockInstitutionalInvestorsBuySell（三大法人買賣）",
    SHAREHOLDING: "FinMind TaiwanStockShareholding（外資持股）",
}
ATTRIBUTION = "資料來源：FinMind"
USER_AGENT = "autotrading-research/0.1 (personal, non-commercial research)"
QUOTA_STATUSES = frozenset({402, 403})
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 4
BASE_BACKOFF_SECONDS = 5.0
MAX_BACKOFF_SECONDS = 60.0
TIMEOUT_SECONDS = 60.0
COOLDOWN_SECONDS = 35 * 60
COOLDOWN_KEY = "finmind:cooldown"


class FinMindRequestError(RuntimeError):
    """FinMind refused or failed a request after the client's own retries."""


class FinMindQuotaError(FinMindRequestError):
    """The hourly quota is used up or the IP is banned: cooling down, not retrying."""


class FinMindCooldownError(FinMindRequestError):
    """A cooldown from an earlier quota error is still running: no request was made."""


__all__ = ["Cooldown", "MemoryCooldown", "RedisCooldown"]


def public_url(dataset: str, code: str, start: date, end: date) -> str:
    """The request URL as stored and shown (FinMind's free tier has no token)."""
    if dataset not in ALLOWED_DATASETS:
        raise ValueError(f"{dataset} is not one of the FinMind datasets this source uses")
    query = urlencode(
        {"dataset": dataset, "data_id": code, "start_date": str(start), "end_date": str(end)}
    )
    return f"{API_BASE}?{query}"


class FinMindClient:
    def __init__(
        self,
        *,
        cooldown: Cooldown | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._cooldown = cooldown or MemoryCooldown()
        self._client = httpx.Client(
            timeout=TIMEOUT_SECONDS,
            follow_redirects=False,
            transport=transport,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        self._sleep = sleep

    @classmethod
    def from_settings(cls) -> Self:
        return cls(cooldown=RedisCooldown.from_settings(COOLDOWN_KEY))

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get(
        self, dataset: str, code: str, start: date, end: date, acquire: Callable[[], None]
    ) -> FetchedPayload:
        url = public_url(dataset, code, start, end)
        if self._cooldown.active():
            raise FinMindCooldownError(
                f"GET {url} not sent: a FinMind quota cooldown is running (up to 35 minutes)"
            )
        for attempt in range(1, MAX_ATTEMPTS + 1):
            acquire()
            try:
                response = self._client.get(url)
            except httpx.TransportError as exc:
                if attempt == MAX_ATTEMPTS:
                    raise FinMindRequestError(f"GET {url} failed: {type(exc).__name__}") from None
                self._sleep(self._backoff(attempt, None))
                continue
            if response.status_code in QUOTA_STATUSES:
                self._cooldown.start(COOLDOWN_SECONDS)
                raise FinMindQuotaError(
                    f"GET {url} returned HTTP {response.status_code}: the hourly quota is used "
                    "up or the IP is banned; cooling down 35 minutes, not retrying"
                )
            if response.status_code == 200:
                self._check(response.content, url)
                return FetchedPayload(
                    content=response.content,
                    content_type=response.headers.get("content-type", "application/json"),
                    source_url=url,
                    fetched_at=datetime.now(UTC),
                )
            if response.status_code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS:
                raise FinMindRequestError(
                    f"GET {url} returned HTTP {response.status_code} after {attempt} attempt(s)"
                )
            delay = self._backoff(attempt, response.headers.get("retry-after"))
            logger.warning(
                "FinMind returned HTTP %s for %s; retrying in %.1fs",
                response.status_code,
                url,
                delay,
            )
            self._sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _check(content: bytes, url: str) -> None:
        """FinMind answers 200 with its own status in the body: only a success envelope with
        a data list is a payload."""
        try:
            body = json.loads(content)
        except ValueError:
            raise FinMindRequestError(f"GET {url} did not return JSON") from None
        if (
            not isinstance(body, dict)
            or body.get("status") != 200
            or body.get("msg") != "success"
            or not isinstance(body.get("data"), list)
        ):
            detail = body.get("msg") if isinstance(body, dict) else "not an object"
            raise FinMindRequestError(f"GET {url} returned a FinMind error: {detail}")

    @staticmethod
    def _backoff(attempt: int, retry_after: str | None) -> float:
        if retry_after is not None and retry_after.isdigit():
            return min(float(retry_after), MAX_BACKOFF_SECONDS)
        return min(BASE_BACKOFF_SECONDS * 2.0 ** (attempt - 1), MAX_BACKOFF_SECONDS)
