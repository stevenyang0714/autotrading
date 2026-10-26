"""HTTP access for news (M0.8, ADR-018): the GDELT DOC 2.0 API and the configured feeds only.

Hosts are fixed: GDELT's API host and the hosts of config/news_feeds.yaml; anything else is
refused. sec.gov requests carry SEC_USER_AGENT (fair access policy); others a plain product
User-Agent. Every request takes a token from the per-source rate limiter first. 429 and 5xx are
retried with backoff (GDELT answers 429 even below its stated one request per 5 seconds).
A feed request may send If-Modified-Since; a 304 answer returns no payload.
A client made by for_hosts lives for one run's fetch and has a time budget inside the run's time
limit: past it, no request starts and no backoff sleep runs past it, so a throttled GDELT run
stops and keeps what it has instead of being stopped by Dramatiq and repeated from the start.
"""

import logging
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from email.utils import format_datetime
from typing import Self
from urllib.parse import urlencode, urlsplit

import httpx2 as httpx

from autotrading.ingestion.job import RUN_TIME_LIMIT_SECONDS, FetchedPayload
from autotrading.settings import get_settings

logger = logging.getLogger(__name__)
for noisy in ("httpx2", "httpcore2"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

GDELT_HOST = "api.gdeltproject.org"
GDELT_DOC_URL = f"https://{GDELT_HOST}/api/v2/doc/doc"
PRODUCT_USER_AGENT = "autotrading-news/0.1 (personal research; metadata only)"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 5
BASE_BACKOFF_SECONDS = 15.0
MAX_BACKOFF_SECONDS = 120.0
TIMEOUT_SECONDS = 60.0
# Leaves the last request (TIMEOUT_SECONDS), a rate-limit wait and store() inside the time limit.
FETCH_TIME_BUDGET_SECONDS = RUN_TIME_LIMIT_SECONDS - 120.0
BUDGET_USED = "stopped: the run's time budget is used up"


class NewsRequestError(RuntimeError):
    """A news request was refused, or kept failing after the client's own retries."""


def public_url(url: str, params: dict[str, str] | None = None) -> str:
    """The request URL as stored and shown (no credentials are ever part of it)."""
    return f"{url}?{urlencode(params)}" if params else url


class NewsClient:
    def __init__(
        self,
        allowed_hosts: Iterable[str],
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        sec_user_agent: str | None = None,
        time_budget: float | None = None,
    ) -> None:
        self._allowed = frozenset(allowed_hosts)
        self._sec_user_agent = sec_user_agent
        self._client = httpx.Client(
            timeout=TIMEOUT_SECONDS, follow_redirects=False, transport=transport
        )
        self._sleep = sleep
        self._clock = clock
        self._deadline = None if time_budget is None else clock() + time_budget

    @classmethod
    def for_hosts(cls, allowed_hosts: Iterable[str]) -> Self:
        """A client for one run's fetch, with the run's time budget."""
        secret = get_settings().sec_user_agent
        return cls(
            allowed_hosts,
            sec_user_agent=secret.get_secret_value() if secret else None,
            time_budget=FETCH_TIME_BUDGET_SECONDS,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _headers(self, host: str, if_modified_since: datetime | None) -> dict[str, str]:
        sec = host == "sec.gov" or host.endswith(".sec.gov")
        if sec and not self._sec_user_agent:
            raise NewsRequestError("SEC_USER_AGENT is not set; sec.gov needs a contact address")
        headers = {
            "User-Agent": (self._sec_user_agent or "") if sec else PRODUCT_USER_AGENT,
            "Accept-Encoding": "gzip",
        }
        if if_modified_since is not None:
            headers["If-Modified-Since"] = format_datetime(
                if_modified_since.astimezone(UTC), usegmt=True
            )
        return headers

    def get(
        self,
        url: str,
        params: dict[str, str] | None,
        acquire: Callable[[], None],
        *,
        if_modified_since: datetime | None = None,
    ) -> FetchedPayload | None:
        """The response as a payload; None when the server answers 304 Not Modified."""
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.scheme != "https" or host not in self._allowed:
            raise NewsRequestError(f"refused: {url} is not a configured news endpoint")
        shown = public_url(url, params)
        headers = self._headers(host, if_modified_since)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if not self._time_left(0.0):
                raise NewsRequestError(f"GET {shown} not sent: {BUDGET_USED}")
            acquire()
            try:
                response = self._client.get(url, params=params, headers=headers)
            except httpx.TransportError as exc:
                failed = f"GET {shown} failed: {type(exc).__name__}"
                if attempt == MAX_ATTEMPTS:
                    raise NewsRequestError(failed) from None
                delay = self._backoff(attempt, None)
                if not self._time_left(delay):
                    raise NewsRequestError(f"{failed}; {BUDGET_USED}") from None
                self._sleep(delay)
                continue
            if response.status_code == 304:
                return None
            if response.status_code == 200:
                return FetchedPayload(
                    content=response.content,
                    content_type=response.headers.get("content-type", "application/octet-stream"),
                    source_url=shown,
                    fetched_at=datetime.now(UTC),
                )
            if response.status_code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS:
                raise NewsRequestError(
                    f"GET {shown} returned HTTP {response.status_code} after {attempt} attempt(s)"
                ) from None
            delay = self._backoff(attempt, response.headers.get("retry-after"))
            if not self._time_left(delay):
                raise NewsRequestError(
                    f"GET {shown} returned HTTP {response.status_code} after {attempt} "
                    f"attempt(s); {BUDGET_USED}"
                ) from None
            logger.warning("HTTP %s for %s; retrying in %.0fs", response.status_code, shown, delay)
            self._sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    def _time_left(self, wait: float) -> bool:
        """Whether waiting `wait` seconds still ends before the budget's deadline."""
        return self._deadline is None or self._clock() + wait < self._deadline

    @staticmethod
    def _backoff(attempt: int, retry_after: str | None) -> float:
        if retry_after is not None and retry_after.isdigit():
            return min(float(retry_after), MAX_BACKOFF_SECONDS)
        return min(BASE_BACKOFF_SECONDS * 2.0 ** (attempt - 1), MAX_BACKOFF_SECONDS)
