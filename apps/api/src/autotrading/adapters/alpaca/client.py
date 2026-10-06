"""HTTP access to Alpaca Market Data (M0.7, ADR-004, ADR-017).

Only the market data host is reachable: the client refuses any other host, so no trading,
account or order endpoint can be called by mistake (paper keys are broker keys too). Keys
travel as headers, never in URLs, and are never logged. Every request takes a token from the
per-source rate limiter first; 429 and 5xx are retried with backoff.
"""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Self
from urllib.parse import urlencode, urlparse

import httpx2 as httpx

from autotrading.ingestion.job import FetchedPayload
from autotrading.settings import Settings, get_settings

logger = logging.getLogger(__name__)
for noisy in ("httpx2", "httpcore2"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

DATA_HOST = "data.alpaca.markets"
BASE_URL = f"https://{DATA_HOST}"
# Market data only: stock bars, quotes, trades, snapshots and corporate actions.
ALLOWED_PATHS = ("/v2/stocks/", "/v1/corporate-actions")
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 4
BASE_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 60.0
TIMEOUT_SECONDS = 30.0


class AlpacaConfigError(RuntimeError):
    """Alpaca access is not configured; the message says what to set, never the value."""


class AlpacaRequestError(RuntimeError):
    """Alpaca kept refusing or failing a request after the client's own retries."""


def configured(settings: Settings | None = None) -> bool:
    current = settings or get_settings()
    key, secret = current.apca_api_key_id, current.apca_api_secret_key
    return bool(
        key and key.get_secret_value().strip() and secret and secret.get_secret_value().strip()
    )


def public_url(path: str, params: dict[str, str]) -> str:
    """The request URL as stored and shown (keys are headers, so nothing to strip)."""
    return f"{BASE_URL}{path}?{urlencode(params)}" if params else f"{BASE_URL}{path}"


class AlpacaClient:
    def __init__(
        self,
        key_id: str,
        secret: str,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not key_id.strip() or not secret.strip():
            raise AlpacaConfigError(
                "APCA_API_KEY_ID / APCA_API_SECRET_KEY are not set: add the paper-account "
                "market data keys to .env (ADR-004)."
            )
        if key_id.strip().startswith("AK"):
            raise AlpacaConfigError(
                "APCA_API_KEY_ID looks like a live-account key; use paper-account keys only."
            )
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers={"APCA-API-KEY-ID": key_id.strip(), "APCA-API-SECRET-KEY": secret.strip()},
            timeout=TIMEOUT_SECONDS,
            follow_redirects=False,
            transport=transport,
        )
        self._sleep = sleep

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> Self:
        current = settings or get_settings()
        key, secret = current.apca_api_key_id, current.apca_api_secret_key
        return cls(
            key.get_secret_value() if key else "", secret.get_secret_value() if secret else ""
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get(self, path: str, params: dict[str, str], acquire: Callable[[], None]) -> FetchedPayload:
        if not path.startswith(ALLOWED_PATHS):
            raise AlpacaRequestError(f"refused: {path} is not a market data endpoint")
        url = public_url(path, params)
        if urlparse(url).hostname != DATA_HOST:  # defence in depth; BASE_URL is fixed
            raise AlpacaRequestError(f"refused: {url} is not the market data host")
        for attempt in range(1, MAX_ATTEMPTS + 1):
            acquire()
            try:
                response = self._client.get(path, params=params)
            except httpx.TransportError as exc:
                if attempt == MAX_ATTEMPTS:
                    raise AlpacaRequestError(f"GET {url} failed: {type(exc).__name__}") from None
                self._sleep(self._backoff(attempt, None))
                continue
            if response.status_code == 200:
                return FetchedPayload(
                    content=response.content,
                    content_type=response.headers.get("content-type", "application/json"),
                    source_url=url,
                    fetched_at=datetime.now(UTC),
                )
            if response.status_code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS:
                raise AlpacaRequestError(
                    f"GET {url} returned HTTP {response.status_code} after {attempt} attempt(s)"
                ) from None
            delay = self._backoff(attempt, response.headers.get("retry-after"))
            logger.warning(
                "Alpaca HTTP %s for %s; retrying in %.1fs", response.status_code, url, delay
            )
            self._sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _backoff(attempt: int, retry_after: str | None) -> float:
        if retry_after is not None and retry_after.isdigit():
            return min(float(retry_after), MAX_BACKOFF_SECONDS)
        return min(BASE_BACKOFF_SECONDS * 2.0 ** (attempt - 1), MAX_BACKOFF_SECONDS)
