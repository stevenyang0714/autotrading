"""News API (M0.8, ADR-018): news as known at a time, copies of one story collapsed.

Each group is one story: its lead is the copy from the strongest tier (then the earliest); the
other copies are listed with their own links. Filters choose which stories appear (a story
matches when any of its articles does); a story always shows all its copies public at known_at.
Counts are stories (duplicate groups) and articles: independence counts stories, not articles.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import AwareDatetime, BaseModel
from sqlalchemy import func, select

from autotrading.api.data_health import SessionDep
from autotrading.db.models import NewsItem, NewsMention, Source
from autotrading.repositories.news import (
    NewsFilter,
    counts,
    group_items,
    latest_group_ids,
    mentions_of,
)

router = APIRouter(tags=["news"])

GDELT_ATTRIBUTION = "News discovery via the GDELT Project"
GDELT_URL = "https://www.gdeltproject.org/"


class MentionOut(BaseModel):
    ticker: str
    rule: str
    confidence: Decimal


class NewsItemOut(BaseModel):
    id: UUID
    url: str
    title: str
    publisher: str
    publisher_domain: str
    author: str | None
    snippet: str | None
    language: str
    source_country: str | None
    kind: str
    source_id: str
    source_tier: int
    published_at: datetime
    time_basis: str
    publisher_updated_at: datetime | None
    data_mode: str
    mentions: list[MentionOut]


class NewsGroupOut(BaseModel):
    group_id: UUID
    lead: NewsItemOut
    others: list[NewsItemOut]
    article_count: int
    publisher_count: int
    best_tier: int
    tickers: list[str]
    first_published_at: datetime
    last_published_at: datetime


class NewsSourceOut(BaseModel):
    id: str
    name: str
    tier: int
    enabled: bool


class NewsFeed(BaseModel):
    known_at: datetime
    ticker: str | None
    source_id: str | None
    max_tier: int | None
    kinds: list[str]
    story_count: int
    article_count: int
    newest_published_at: datetime | None
    groups: list[NewsGroupOut]
    sources: list[NewsSourceOut]
    attribution: str
    attribution_url: str


def item_out(item: NewsItem, mentions: list[NewsMention]) -> NewsItemOut:
    return NewsItemOut(
        id=item.id,
        url=item.url,
        title=item.title,
        publisher=item.publisher,
        publisher_domain=item.publisher_domain,
        author=item.author,
        snippet=item.snippet,
        language=item.language,
        source_country=item.source_country,
        kind=item.kind,
        source_id=item.source_id,
        source_tier=item.source_tier,
        published_at=item.published_at,
        time_basis=item.time_basis,
        publisher_updated_at=item.publisher_updated_at,
        data_mode=item.data_mode,
        mentions=[
            MentionOut(ticker=m.ticker, rule=m.rule, confidence=m.confidence) for m in mentions
        ],
    )


@router.get("/news")
def news(
    session: SessionDep,
    ticker: Annotated[str | None, Query(description="Universe ticker, e.g. AAPL")] = None,
    source: Annotated[str | None, Query(description="Source id, e.g. gdelt or sec_press")] = None,
    max_tier: Annotated[int | None, Query(ge=1, le=4, description="Tiers 1..max_tier")] = None,
    kind: Annotated[
        str | None,
        Query(
            pattern=r"^(article|press_release|official)(,(article|press_release|official))*$",
            description="Comma-separated: article (media), press_release (issuer), official",
        ),
    ] = None,
    known_at: Annotated[
        AwareDatetime | None, Query(description="Point in time (ADR-012); default now")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> NewsFeed:
    at: datetime = known_at or session.execute(select(func.now())).scalar_one()
    wanted = NewsFilter(
        known_at=at,
        ticker=ticker.upper() if ticker else None,
        source_id=source or None,
        max_tier=max_tier,
        kinds=tuple(kind.split(",")) if kind else (),
    )
    group_ids = latest_group_ids(session, wanted, limit=limit)
    items = group_items(session, group_ids, known_at=at)
    mentions = mentions_of(session, [item.id for item in items])
    by_group: dict[UUID, list[NewsItem]] = {}
    for item in items:  # ordered by tier, then time: the first is the lead
        by_group.setdefault(item.duplicate_group_id, []).append(item)
    groups = []
    for group_id in group_ids:
        members = by_group.get(group_id, [])
        if not members:
            continue
        outs = [item_out(m, mentions.get(m.id, [])) for m in members]
        times = [m.published_at for m in members]
        groups.append(
            NewsGroupOut(
                group_id=group_id,
                lead=outs[0],
                others=outs[1:],
                article_count=len(members),
                publisher_count=len({m.publisher_domain for m in members}),
                best_tier=min(m.source_tier for m in members),
                tickers=sorted({mention.ticker for out in outs for mention in out.mentions}),
                first_published_at=min(times),
                last_published_at=max(times),
            )
        )
    stories, articles = counts(session, wanted)
    sources = [
        NewsSourceOut(id=s.id, name=s.name, tier=s.tier, enabled=s.enabled)
        for s in session.scalars(select(Source).order_by(Source.priority, Source.id))
        if "news" in (s.topics or [])
    ]
    newest = session.scalar(
        select(func.max(NewsItem.published_at)).where(NewsItem.published_at <= at)
    )
    return NewsFeed(
        known_at=at,
        ticker=wanted.ticker,
        source_id=wanted.source_id,
        max_tier=max_tier,
        kinds=list(wanted.kinds),
        story_count=stories,
        article_count=articles,
        newest_published_at=newest,
        groups=groups,
        sources=sources,
        attribution=GDELT_ATTRIBUTION,
        attribution_url=GDELT_URL,
    )
