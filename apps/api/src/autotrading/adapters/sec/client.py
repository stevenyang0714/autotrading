"""HTTP access to SEC EDGAR under the fair access policy (errata E8).

Every request carries SEC_USER_AGENT ("Name email@example.com") and takes a token from the
per-source rate limiter first (5 requests/second, config/sources.yaml). 403 and 429 are
SEC's throttling answers and 5xx are transient: those are retried with exponential backoff,
honouring Retry-After. Anything else fails the run, and the runner's own retries take over.
"""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal, Self, overload

import httpx2 as httpx

from autotrading.ingestion.job import FetchedPayload
from autotrading.settings import Settings, get_settings

logger = logging.getLogger(__name__)

RETRY_STATUSES = frozenset({403, 429, 500, 502, 503, 504})
MAX_ATTEMPTS = 4
BASE_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 60.0
TIMEOUT_SECONDS = 60.0


class SecConfigError(RuntimeError):
    """SEC access is not configured; the message says what to set, never the value."""


class SecRequestError(RuntimeError):
    """SEC kept refusing or failing a request after the client's own retries."""


def validate_user_agent(value: str | None) -> str:
    user_agent = (value or "").strip()
    if not user_agent:
        raise SecConfigError(
            "SEC_USER_AGENT is not set. Add `SEC_USER_AGENT=Your Name you@example.com` to .env "
            "(SEC fair access policy requires a name and an email)."
        )
    if "@" not in user_agent:
        raise SecConfigError("SEC_USER_AGENT must contain a contact email address.")
    return user_agent


class SecClient:
    def __init__(
        self,
        user_agent: str,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = httpx.Client(
            headers={"User-Agent": validate_user_agent(user_agent), "Accept-Encoding": "gzip"},
            timeout=TIMEOUT_SECONDS,
            follow_redirects=False,
            transport=transport,
        )
        self._sleep = sleep

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> Self:
        secret = (settings or get_settings()).sec_user_agent
        return cls(validate_user_agent(secret.get_secret_value() if secret else None))

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @overload
    def get(
        self, url: str, acquire: Callable[[], None], *, allow_missing: Literal[False] = False
    ) -> FetchedPayload: ...

    @overload
    def get(
        self, url: str, acquire: Callable[[], None], *, allow_missing: bool
    ) -> FetchedPayload | None: ...

    def get(
        self, url: str, acquire: Callable[[], None], *, allow_missing: bool = False
    ) -> FetchedPayload | None:
        """GET with retries. `allow_missing`: a 404 returns None (e.g. no XBRL filings yet)."""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            acquire()
            try:
                response = self._client.get(url)
            except httpx.TransportError as exc:
                if attempt == MAX_ATTEMPTS:
                    raise SecRequestError(f"GET {url} failed: {type(exc).__name__}") from exc
                self._sleep(self._backoff(attempt, None))
                continue
            if response.status_code == 200:
                return FetchedPayload(
                    content=response.content,
                    content_type=response.headers.get("content-type", "application/json"),
                    source_url=url,
                    fetched_at=datetime.now(UTC),
                )
            if response.status_code == 404 and allow_missing:
                return None
            if response.status_code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS:
                raise SecRequestError(
                    f"GET {url} returned HTTP {response.status_code} after {attempt} attempt(s)"
                )
            delay = self._backoff(attempt, response.headers.get("retry-after"))
            logger.warning(
                "SEC returned HTTP %s for %s; retrying in %.1fs", response.status_code, url, delay
            )
            self._sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _backoff(attempt: int, retry_after: str | None) -> float:
        if retry_after is not None and retry_after.isdigit():
            return min(float(retry_after), MAX_BACKOFF_SECONDS)
        return min(BASE_BACKOFF_SECONDS * 2.0 ** (attempt - 1), MAX_BACKOFF_SECONDS)
