"""Jobs `news.rss.<source_id>` (M0.8, ADR-018): official RSS 2.0 / Atom feeds from
config/news_feeds.yaml, one job per feed (each feed is its own source).

fetch: GET the feed (If-Modified-Since the last stored copy; 304 means nothing new), then strip
       it before it is stored anywhere: full-text elements (content:encoded) are removed and
       every summary (description, summary, Atom content) is cut to a short plain-text snippet.
       The stored "raw" payload is this metadata-only feed.
store: one news item per entry with the publisher's own time; issuer feeds mention their
       company (feed_issuer), and titles are matched for other universe companies.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from io import BytesIO
from typing import ClassVar, cast
from urllib.parse import urljoin, urlsplit

from autotrading.adapters.news.client import NewsClient
from autotrading.adapters.news.config import FeedConfig, feeds, universe_companies
from autotrading.db.models import Source
from autotrading.domain.news import Mention, find_mentions, plain_text, publisher_domain, snippet
from autotrading.domain.provenance import LicenseStatus, Provenance
from autotrading.ingestion.job import (
    FetchContext,
    FetchedPayload,
    IngestionJob,
    StoreContext,
    StoreResult,
    register_job,
)
from autotrading.repositories.news import NewsIn, NewsRepository

ATOM = "http://www.w3.org/2005/Atom"
CONTENT = "http://purl.org/rss/1.0/modules/content/"
DC = "http://purl.org/dc/elements/1.1/"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
FULL_TEXT_TAGS = frozenset({f"{{{CONTENT}}}encoded"})
SUMMARY_TAGS = frozenset({"description", f"{{{ATOM}}}summary", f"{{{ATOM}}}content"})


def _namespaces(content: bytes) -> dict[str, str]:
    return {
        prefix: uri
        for _event, (prefix, uri) in ET.iterparse(BytesIO(content), events=("start-ns",))
    }


def strip_full_text(content: bytes) -> bytes:
    """The feed without article text: full-text elements removed, summaries cut to a short
    plain-text snippet. Applying it twice changes nothing."""
    for prefix, uri in _namespaces(content).items():
        # ns0, ns1, ... are ElementTree's own names for unregistered namespaces (an already
        # stripped feed carries them); registering them is refused, and not needed.
        if prefix and not re.fullmatch(r"ns\d+", prefix):
            ET.register_namespace(prefix, uri)
    root = ET.fromstring(content)
    for parent in root.iter():
        for child in list(parent):
            if child.tag in FULL_TEXT_TAGS:
                parent.remove(child)
            elif child.tag in SUMMARY_TAGS:
                text = "".join(child.itertext())
                for grandchild in list(child):
                    child.remove(grandchild)
                child.attrib.pop("type", None)
                child.text = snippet(text)
    return cast(bytes, ET.tostring(root, encoding="utf-8", xml_declaration=True))


@dataclass(frozen=True)
class FeedEntry:
    title: str
    link: str
    published: datetime | None
    updated: datetime | None
    author: str | None
    summary: str | None


@dataclass(frozen=True)
class Feed:
    title: str | None
    language: str | None
    entries: list[FeedEntry]


def _date(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    value = value.strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _text(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    value = plain_text("".join(element.itertext()))
    return value or None


def _atom_link(entry: ET.Element) -> str | None:
    for link in entry.findall(f"{{{ATOM}}}link"):
        if link.get("rel", "alternate") == "alternate" and link.get("href"):
            return link.get("href")
    return None


def parse_feed(content: bytes, base_url: str) -> Feed:
    """Entries of an RSS 2.0 or Atom feed (titles, links, times, author, summary)."""
    root = ET.fromstring(content)
    entries: list[FeedEntry] = []
    if root.tag == f"{{{ATOM}}}feed":
        for entry in root.findall(f"{{{ATOM}}}entry"):
            title, link = _text(entry.find(f"{{{ATOM}}}title")), _atom_link(entry)
            if not title or not link:
                continue
            entries.append(
                FeedEntry(
                    title=title,
                    link=urljoin(base_url, link),
                    published=_date(entry.findtext(f"{{{ATOM}}}published")),
                    updated=_date(entry.findtext(f"{{{ATOM}}}updated")),
                    author=_text(entry.find(f"{{{ATOM}}}author/{{{ATOM}}}name")),
                    summary=_text(entry.find(f"{{{ATOM}}}summary"))
                    or _text(entry.find(f"{{{ATOM}}}content")),
                )
            )
        return Feed(_text(root.find(f"{{{ATOM}}}title")), root.get(XML_LANG), entries)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("not an RSS 2.0 or Atom feed")
    for item in channel.findall("item"):
        title = _text(item.find("title"))
        link = (item.findtext("link") or "").strip()
        if not link:
            guid = item.find("guid")
            if guid is not None and guid.get("isPermaLink", "true") == "true":
                link = (guid.text or "").strip()
        if not title or not link:
            continue
        entries.append(
            FeedEntry(
                title=title,
                link=urljoin(base_url, link),
                published=_date(item.findtext("pubDate")) or _date(item.findtext(f"{{{DC}}}date")),
                updated=None,
                author=_text(item.find("author")) or _text(item.find(f"{{{DC}}}creator")),
                summary=_text(item.find("description")),
            )
        )
    return Feed(_text(channel.find("title")), channel.findtext("language"), entries)


def language_code(value: str | None) -> str:
    """ "en-us" -> "en"; feeds without a language are English (only English feeds are used)."""
    return (value or "en").strip().lower()[:2] or "en"


class RssJob(IngestionJob):
    """One configured feed; concrete classes per feed are made by `job_for`."""

    feed: ClassVar[FeedConfig]
    # Recorded fixtures override it with "fixture" (ADR-006).
    data_mode: ClassVar[str] = "live"

    def client(self) -> NewsClient:
        return NewsClient.for_hosts([urlsplit(self.feed.url).hostname or ""])

    def fetch(self, ctx: FetchContext) -> list[FetchedPayload]:
        since = self.params.get("if_modified_since")
        with self.client() as client:
            payload = client.get(
                self.feed.url,
                None,
                ctx.acquire,
                if_modified_since=datetime.fromisoformat(since) if since else None,
            )
        if payload is None:
            return []
        return [replace(payload, content=strip_full_text(payload.content))]

    def store(self, ctx: StoreContext) -> StoreResult:
        source = ctx.session.get_one(Source, self.source_id)
        companies = universe_companies(ctx.session)
        matchable = [company for company, _ in companies.values()]
        instrument_of = {ticker: instrument for ticker, (_, instrument) in companies.items()}
        items: list[NewsIn] = []
        for payload in ctx.payloads:
            feed = parse_feed(payload.content, self.feed.url)
            for entry in feed.entries:
                mentions = find_mentions(entry.title, matchable)
                if self.feed.ticker and self.feed.ticker in instrument_of:
                    mentions = [m for m in mentions if m.ticker != self.feed.ticker]
                    mentions.insert(
                        0, Mention(self.feed.ticker, "feed_issuer", self.feed.publisher)
                    )
                published = entry.published or entry.updated
                basis = "publisher" if published else "first_seen"
                # A publisher time after we fetched the feed cannot be right: cap it.
                at = min(published or payload.fetched_at, payload.fetched_at)
                items.append(
                    NewsIn(
                        url=entry.link,
                        title=entry.title[:500],
                        publisher=self.feed.publisher,
                        publisher_domain=publisher_domain(entry.link),
                        author=entry.author[:200] if entry.author else None,
                        snippet=snippet(entry.summary),
                        language=language_code(feed.language),
                        source_country=None,
                        kind=self.feed.kind,
                        time_basis=basis,
                        publisher_updated_at=entry.updated,
                        data_mode=self.data_mode,
                        provenance=Provenance(
                            source_id=source.id,
                            source_tier=source.tier,
                            source_url=payload.source_url,
                            published_at=at,
                            published_at_precision="exact",
                            ingested_at=payload.fetched_at,
                            effective_from=at,
                            as_of=at,
                            license_status=cast(LicenseStatus, source.license_status),
                            confidence=1.0,
                            ingestion_run_id=ctx.run_id,
                            raw_payload_sha256=payload.sha256,
                        ),
                        mentions=tuple(
                            (instrument_of[m.ticker], m)
                            for m in mentions
                            if m.ticker in instrument_of
                        ),
                    )
                )
        result = NewsRepository(ctx.session).insert(items, actor=f"ingest:{self.source_id}")
        return StoreResult(inserted=result.inserted, unchanged=result.unchanged)


def job_name(source_id: str) -> str:
    return f"news.rss.{source_id}"


def job_for(feed: FeedConfig, base: type[RssJob] = RssJob) -> type[RssJob]:
    """A job class for one feed, named news.rss.<source_id>."""
    return cast(
        type[RssJob],
        type(
            f"{base.__name__}_{feed.source_id}",
            (base,),
            {"source_id": feed.source_id, "name": job_name(feed.source_id), "feed": feed},
        ),
    )


RSS_JOBS: dict[str, type[RssJob]] = {
    source_id: register_job(job_for(feed)) for source_id, feed in feeds().items()
}
