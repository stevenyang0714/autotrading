"""HTTP access to the FRED / ALFRED API (M0.6, ADR-015).

FRED takes the API key only as a query parameter, so the key must never reach a stored URL,
an error message or a log line:
- payloads carry `public_url`, the request URL without `api_key`;
- errors name that public URL and are raised `from None`, so no chained exception (whose text
  could hold the full URL) reaches the worker's traceback;
- httpx2/httpcore2 request logging is limited to warnings in this process.
Every request takes a token from the per-source rate limiter first (config/sources.yaml).
"""

import logging
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Self
from urllib.parse import urlencode

import httpx2 as httpx

from autotrading.ingestion.job import FetchedPayload
from autotrading.settings import Settings, get_settings

logger = logging.getLogger(__name__)
# httpx2 logs "HTTP Request: GET <url>" at INFO, and the URL would include the key.
for noisy in ("httpx2", "httpcore2"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

API_BASE = "https://api.stlouisfed.org/fred"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 4
BASE_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 60.0
TIMEOUT_SECONDS = 60.0
KEY_FORMAT = re.compile(r"^[a-z0-9]{32}$")
KEY_LIKE = re.compile(r"\b[a-z0-9]{32}\b")


class FredConfigError(RuntimeError):
    """FRED access is not configured; the message says what to set, never the value."""


class FredRequestError(RuntimeError):
    """FRED kept refusing or failing a request after the client's own retries."""


def validate_api_key(value: str | None) -> str:
    key = (value or "").strip()
    if not key:
        raise FredConfigError(
            "FRED_API_KEY is not set. Request a free key at "
            "https://fredaccount.stlouisfed.org (API Keys) and add it to .env."
        )
    if not KEY_FORMAT.match(key):
        raise FredConfigError("FRED_API_KEY must be the 32-character lowercase key from FRED.")
    return key


def public_url(path: str, params: dict[str, str]) -> str:
    """The request URL as stored and shown: never contains the API key."""
    return f"{API_BASE}/{path}?{urlencode({**params, 'file_type': 'json'})}"


class FredClient:
    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._key = validate_api_key(api_key)
        self._client = httpx.Client(
            timeout=TIMEOUT_SECONDS, follow_redirects=False, transport=transport
        )
        self._sleep = sleep

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> Self:
        secret = (settings or get_settings()).fred_api_key
        return cls(validate_api_key(secret.get_secret_value() if secret else None))

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get(self, path: str, params: dict[str, str], acquire: Callable[[], None]) -> FetchedPayload:
        url = public_url(path, params)
        query = {**params, "file_type": "json", "api_key": self._key}
        for attempt in range(1, MAX_ATTEMPTS + 1):
            acquire()
            try:
                response = self._client.get(f"{API_BASE}/{path}", params=query)
            except httpx.TransportError as exc:
                if attempt == MAX_ATTEMPTS:
                    raise FredRequestError(f"GET {url} failed: {type(exc).__name__}") from None
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
                raise FredRequestError(
                    f"GET {url} returned HTTP {response.status_code} after {attempt} attempt(s)"
                    f"{self._reason(response)}"
                ) from None
            delay = self._backoff(attempt, response.headers.get("retry-after"))
            logger.warning(
                "FRED returned HTTP %s for %s; retrying in %.1fs", response.status_code, url, delay
            )
            self._sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _reason(response: httpx.Response) -> str:
        """FRED's own error text, with anything key-shaped removed."""
        try:
            message = str(response.json().get("error_message", ""))
        except ValueError:
            return ""
        return f": {KEY_LIKE.sub('***', message)[:200]}" if message else ""

    @staticmethod
    def _backoff(attempt: int, retry_after: str | None) -> float:
        if retry_after is not None and retry_after.isdigit():
            return min(float(retry_after), MAX_BACKOFF_SECONDS)
        return min(BASE_BACKOFF_SECONDS * 2.0 ** (attempt - 1), MAX_BACKOFF_SECONDS)
