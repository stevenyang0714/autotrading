"""Insert-only access to news (M0.8, ADR-018).

Inserting assigns duplicate groups (domain/news.py): every new article is compared with the
stored articles published within GROUP_WINDOW and with the ones before it in the same batch.
A transaction-level advisory lock serialises inserts, so two runs cannot split one story into
two groups. An article whose canonical URL is already stored is left alone (unchanged).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from autotrading.db.models import NewsItem, NewsMention
from autotrading.domain.news import (
    EXTRACTOR_VERSION,
    GROUP_WINDOW,
    GroupCandidate,
    Mention,
    canonical_url,
    duplicate_group,
    normalize_title,
)
from autotrading.domain.provenance import Provenance
from autotrading.repositories.audit import set_actor

NEWS_LOCK = "news_items_insert"


@dataclass(frozen=True)
class NewsIn:
    url: str
    title: str
    publisher: str
    publisher_domain: str
    author: str | None
    snippet: str | None
    language: str
    source_country: str | None
    kind: str
    time_basis: str
    publisher_updated_at: datetime | None
    data_mode: str
    provenance: Provenance
    mentions: tuple[tuple[UUID, Mention], ...] = field(default=())  # (instrument id, mention)


@dataclass(frozen=True)
class NewsInsertResult:
    inserted: int
    unchanged: int
    mentions: int


class NewsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def insert(self, items: Sequence[NewsIn], *, actor: str) -> NewsInsertResult:
        set_actor(self.session, actor)
        if not items:
            return NewsInsertResult(0, 0, 0)
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": NEWS_LOCK}
        )
        # One article per canonical URL: the earliest copy in the batch wins.
        by_url: dict[str, NewsIn] = {}
        for item in sorted(items, key=lambda i: i.provenance.published_at):
            by_url.setdefault(canonical_url(item.url), item)
        stored = set(
            self.session.scalars(
                select(NewsItem.canonical_url).where(NewsItem.canonical_url.in_(list(by_url)))
            )
        )
        new = [(url, item) for url, item in by_url.items() if url not in stored]
        if not new:
            return NewsInsertResult(0, len(items), 0)
        times = [item.provenance.published_at for _, item in new]
        candidates = [
            GroupCandidate(
                row.id,
                row.duplicate_group_id,
                row.canonical_url,
                row.title_key,
                row.published_at,
                row.publisher_domain,
            )
            for row in self.session.execute(
                select(
                    NewsItem.id,
                    NewsItem.duplicate_group_id,
                    NewsItem.canonical_url,
                    NewsItem.title_key,
                    NewsItem.published_at,
                    NewsItem.publisher_domain,
                ).where(
                    NewsItem.published_at.between(
                        min(times) - GROUP_WINDOW, max(times) + GROUP_WINDOW
                    )
                )
            )
        ]
        rows: list[dict[str, Any]] = []
        mention_rows: list[dict[str, Any]] = []
        for url, item in new:
            published = item.provenance.published_at
            key = normalize_title(item.title)
            item_id = uuid4()
            group_id = (
                duplicate_group(
                    canonical=url,
                    title_key=key,
                    published_at=published,
                    domain=item.publisher_domain,
                    existing=candidates,
                )
                or item_id
            )
            candidates.append(
                GroupCandidate(item_id, group_id, url, key, published, item.publisher_domain)
            )
            rows.append(
                {
                    "id": item_id,
                    "url": item.url,
                    "canonical_url": url,
                    "title": item.title,
                    "title_key": key,
                    "publisher": item.publisher,
                    "publisher_domain": item.publisher_domain,
                    "author": item.author,
                    "snippet": item.snippet,
                    "language": item.language,
                    "source_country": item.source_country,
                    "kind": item.kind,
                    "time_basis": item.time_basis,
                    "publisher_updated_at": item.publisher_updated_at,
                    "duplicate_group_id": group_id,
                    "data_mode": item.data_mode,
                    **item.provenance.model_dump(),
                }
            )
            mention_rows += [
                {
                    "news_item_id": item_id,
                    "instrument_id": instrument_id,
                    "ticker": mention.ticker,
                    "rule": mention.rule,
                    "matched_text": mention.matched_text,
                    "confidence": mention.confidence,
                    "extractor_version": EXTRACTOR_VERSION,
                }
                for instrument_id, mention in item.mentions
            ]
        inserted = set(
            self.session.scalars(
                insert(NewsItem)
                .on_conflict_do_nothing(index_elements=["canonical_url"])
                .returning(NewsItem.id),
                rows,
            )
        )
        mention_rows = [m for m in mention_rows if m["news_item_id"] in inserted]
        if mention_rows:
            self.session.execute(insert(NewsMention).on_conflict_do_nothing(), mention_rows)
        self.session.flush()
        return NewsInsertResult(len(inserted), len(items) - len(inserted), len(mention_rows))


# ---------- reads ----------


@dataclass(frozen=True)
class NewsFilter:
    known_at: datetime
    ticker: str | None = None
    source_id: str | None = None
    max_tier: int | None = None
    kinds: tuple[str, ...] = ()  # article, press_release, official; empty: all


def _filtered(query: Any, wanted: NewsFilter) -> Any:
    query = query.where(NewsItem.published_at <= wanted.known_at)
    if wanted.source_id:
        query = query.where(NewsItem.source_id == wanted.source_id)
    if wanted.max_tier:
        query = query.where(NewsItem.source_tier <= wanted.max_tier)
    if wanted.kinds:
        query = query.where(NewsItem.kind.in_(wanted.kinds))
    if wanted.ticker:
        query = query.where(
            NewsItem.id.in_(
                select(NewsMention.news_item_id).where(NewsMention.ticker == wanted.ticker)
            )
        )
    return query


def latest_group_ids(session: Session, wanted: NewsFilter, *, limit: int) -> list[UUID]:
    """Groups with a matching article public at known_at, newest first."""
    query = _filtered(
        select(NewsItem.duplicate_group_id, func.max(NewsItem.published_at).label("latest")),
        wanted,
    )
    rows = session.execute(
        query.group_by(NewsItem.duplicate_group_id)
        .order_by(func.max(NewsItem.published_at).desc())
        .limit(limit)
    )
    return [row.duplicate_group_id for row in rows]


def counts(session: Session, wanted: NewsFilter) -> tuple[int, int]:
    """(stories, articles) matching the filter: stories count duplicate groups once."""
    query = _filtered(
        select(func.count(func.distinct(NewsItem.duplicate_group_id)), func.count(NewsItem.id)),
        wanted,
    )
    stories, articles = session.execute(query).one()
    return int(stories), int(articles)


def group_items(
    session: Session, group_ids: Sequence[UUID], *, known_at: datetime
) -> list[NewsItem]:
    """Every article of the groups public at known_at (all copies, whatever the filter)."""
    if not group_ids:
        return []
    return list(
        session.scalars(
            select(NewsItem)
            .where(
                NewsItem.duplicate_group_id.in_(list(group_ids)),
                NewsItem.published_at <= known_at,
            )
            .order_by(NewsItem.source_tier, NewsItem.published_at)
        )
    )


def mentions_of(session: Session, item_ids: Sequence[UUID]) -> dict[UUID, list[NewsMention]]:
    found: dict[UUID, list[NewsMention]] = {}
    if not item_ids:
        return found
    for mention in session.scalars(
        select(NewsMention)
        .where(
            NewsMention.news_item_id.in_(list(item_ids)),
            NewsMention.extractor_version == EXTRACTOR_VERSION,
        )
        .order_by(NewsMention.ticker)
    ):
        found.setdefault(mention.news_item_id, []).append(mention)
    return found
