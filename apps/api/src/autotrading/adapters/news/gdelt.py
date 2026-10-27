"""Job `news.gdelt` (M0.8, ADR-018): GDELT DOC 2.0 article lists, one query per universe
equity (config/news_entities.yaml), for a time range.

fetch: one artlist request per equity (English sources, newest first, up to `maxrecords`).
store: GDELT returns url, title, the time GDELT first saw the article (seendate), domain,
       language and country; no author, publication time or text. An article is kept only
       when its title names a universe company and its site is not blocked; its tier is its
       publisher's (config/news_publishers.yaml), its time the GDELT first-seen time
       (time_basis first_seen).
GDELT's terms ask for a citation and a link to https://www.gdeltproject.org/ wherever its data
is used: the News page shows it.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any, ClassVar, cast

from autotrading.adapters.news.client import (
    GDELT_DOC_URL,
    GDELT_HOST,
    NewsClient,
    NewsRequestError,
    NewsThrottledError,
)
from autotrading.adapters.news.config import entities, publisher_tiers, universe_companies
from autotrading.db.models import Source
from autotrading.domain.news import find_mentions, publisher_domain
from autotrading.domain.provenance import LicenseStatus, Provenance
from autotrading.ingestion.cooldown import Cooldown, RedisCooldown
from autotrading.ingestion.job import (
    FetchContext,
    FetchedPayload,
    IngestionJob,
    StoreContext,
    StoreResult,
    register_job,
)
from autotrading.repositories.news import NewsIn, NewsRepository

logger = logging.getLogger(__name__)

SOURCE_ID = "gdelt"
ACTOR = f"ingest:{SOURCE_ID}"
GDELT_TIME = "%Y%m%d%H%M%S"
MAX_RECORDS = 250
LANGUAGES = {"English": "en"}


def gdelt_time(value: datetime) -> str:
    return value.astimezone(UTC).strftime(GDELT_TIME)


def query_params(query: str, start: str, end: str, maxrecords: int) -> dict[str, str]:
    return {
        "query": f"{query} sourcelang:english",
        "mode": "artlist",
        "format": "json",
        "maxrecords": str(maxrecords),
        "sort": "datedesc",
        "startdatetime": start,
        "enddatetime": end,
    }


def articles(content: bytes) -> list[dict[str, Any]]:
    """The article list of a response; an empty response or {} means no matches."""
    if not content.strip():
        return []
    try:
        data = json.loads(content, strict=False)  # GDELT titles may carry control characters
    except json.JSONDecodeError:
        raise NewsRequestError(f"GDELT answered with text, not JSON: {content[:120]!r}") from None
    return list(data.get("articles") or [])


def seen_at(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


@register_job
class GdeltJob(IngestionJob):
    source_id: ClassVar[str] = SOURCE_ID
    name: ClassVar[str] = "news.gdelt"
    # Recorded fixtures override it with "fixture" (ADR-006).
    data_mode: ClassVar[str] = "live"
    # KI-30: after GDELT throttles, no GDELT request for this long, in any process.
    cooldown_seconds: ClassVar[int] = 30 * 60
    cooldown_key: ClassVar[str] = "gdelt:cooldown"

    def __init__(self, params: dict[str, Any], window: Any) -> None:
        super().__init__(params, window)
        self.pause_note: str | None = None

    def client(self) -> NewsClient:
        return NewsClient.for_hosts([GDELT_HOST])

    def cooldown(self) -> Cooldown:
        return RedisCooldown.from_settings(self.cooldown_key)

    def fetch(self, ctx: FetchContext) -> list[FetchedPayload]:
        """One query per equity. When GDELT throttles (a repeated 429), the run stops, keeps what
        it has and pauses GDELT for 30 minutes; while paused a run sends nothing and ends with a
        note. Either way the run succeeds, so Dramatiq does not repeat it: the next hourly run
        searches the same 24 hours again, starting from another equity (KI-30). A run that gets
        nothing for another reason fails."""
        pause = self.cooldown()
        if pause.active():
            self.pause_note = "skipped: GDELT is paused after throttling this address (KI-30)"
            return []
        companies = entities().companies
        start, end = str(self.params["start"]), str(self.params["end"])
        maxrecords = int(self.params.get("maxrecords", MAX_RECORDS))
        tickers = list(self.params["tickers"])
        first = int(self.params.get("rotate", 0)) % max(len(tickers), 1)
        payloads: list[FetchedPayload] = []
        with self.client() as client:
            for ticker in tickers[first:] + tickers[:first]:
                params = query_params(companies[ticker].gdelt_query, start, end, maxrecords)
                try:
                    payload = client.get(GDELT_DOC_URL, params, ctx.acquire)
                except NewsThrottledError:
                    pause.start(self.cooldown_seconds)
                    self.pause_note = (
                        f"GDELT throttled at {ticker}: paused 30 minutes; kept {len(payloads)} "
                        "of the queries (KI-30)"
                    )
                    logger.warning("gdelt: %s", self.pause_note)
                    break
                except NewsRequestError as exc:
                    if not payloads:
                        raise
                    logger.warning("gdelt: stopped at %s (%s); kept %d", ticker, exc, len(payloads))
                    break
                if payload is not None:
                    articles(payload.content)  # fail the run on a text answer, not on store
                    payloads.append(payload)
        return payloads

    def store(self, ctx: StoreContext) -> StoreResult:
        source = ctx.session.get_one(Source, SOURCE_ID)
        companies = universe_companies(ctx.session)
        matchable = [company for company, _ in companies.values()]
        instrument_of = {ticker: instrument for ticker, (_, instrument) in companies.items()}
        tiers = publisher_tiers()
        items: list[NewsIn] = []
        skipped = 0
        for payload in ctx.payloads:
            for article in articles(payload.content):
                title = str(article.get("title") or "").strip()
                url = str(article.get("url") or "")
                mentions = [m for m in find_mentions(title, matchable) if m.ticker in instrument_of]
                if not title or not url.startswith(("http://", "https://")) or not mentions:
                    skipped += 1
                    continue
                domain = str(article.get("domain") or "") or publisher_domain(url)
                if tiers.is_blocked(domain):
                    skipped += 1
                    continue
                seen = min(seen_at(str(article["seendate"])), payload.fetched_at)
                tier, name = tiers.lookup(domain)
                language = str(article.get("language") or "English")
                items.append(
                    NewsIn(
                        url=url,
                        title=title[:500],
                        publisher=name or domain,
                        publisher_domain=domain,
                        author=None,
                        snippet=None,
                        language=LANGUAGES.get(language, language.lower()[:2]),
                        source_country=str(article.get("sourcecountry") or "") or None,
                        kind="official" if domain.endswith(".gov") else "article",
                        time_basis="first_seen",
                        publisher_updated_at=None,
                        data_mode=self.data_mode,
                        provenance=Provenance(
                            source_id=source.id,
                            source_tier=tier,
                            source_url=payload.source_url,
                            published_at=seen,
                            published_at_precision="exact",
                            ingested_at=payload.fetched_at,
                            effective_from=seen,
                            as_of=seen,
                            license_status=cast(LicenseStatus, source.license_status),
                            confidence=1.0,
                            ingestion_run_id=ctx.run_id,
                            raw_payload_sha256=payload.sha256,
                        ),
                        mentions=tuple((instrument_of[m.ticker], m) for m in mentions),
                    )
                )
        result = NewsRepository(ctx.session).insert(items, actor=ACTOR)
        logger.info(
            "gdelt: %d new, %d already stored, %d skipped (no universe company or blocked site)",
            result.inserted,
            result.unchanged,
            skipped,
        )
        notes = (self.pause_note,) if self.pause_note else ()
        return StoreResult(inserted=result.inserted, unchanged=result.unchanged, notes=notes)
