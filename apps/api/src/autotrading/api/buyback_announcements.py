"""Buyback announcements as the API shows them (M1.4a, ADR-025 B1): statements of 8-Ks (stored by
`sec.eight_k`, one extractor version) and of the issuer's press releases (title and snippet, read
on request), grouped into events by domain/buyback.py. Each keeps its sentence and link as
evidence. Shared by the Buybacks section and the buyback states (M1.4b).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from autotrading.api.valuation import recorded_by
from autotrading.db.models import FilingBuybackStatement, Instrument, NewsItem, NewsMention
from autotrading.domain.buyback import AnnouncementSource, Event
from autotrading.domain.buyback_announcements import EXTRACTOR_VERSION, statement


class AnnouncementSourceOut(BaseModel):
    channel: Literal["sec_8k", "press_release"]
    sentence: str  # the issuer's words, at most 300 characters
    url: str
    published_at: datetime
    stated_date: date | None
    accession: str | None
    document_type: str | None  # 8-K, EX-99.1, ...
    title: str | None  # press release


class AnnouncementEvent(BaseModel):
    kind: Literal["new", "increase", "plan", "remaining"]
    amount: Decimal  # USD
    remaining_amount: Decimal | None
    day: date  # stated, else the first publication day in New York
    first_published_at: datetime
    sources: list[AnnouncementSourceOut]


def announcement_sources(
    session: Session,
    instrument: Instrument,
    chain: list[UUID],
    at: datetime,
    system_time: datetime | None = None,
    extractor_version: str = EXTRACTOR_VERSION,
) -> list[AnnouncementSource]:
    """Statements of 8-Ks by the issuer chain (of one extractor version) and of the issuer's
    press releases, known at T, as this database held them at `system_time` (default: now)."""
    filed = [
        AnnouncementSource(
            channel="sec_8k",
            kind=row.kind,
            amount=row.amount,
            remaining_amount=row.remaining_amount,
            stated_date=row.stated_date,
            sentence=row.sentence,
            url=row.source_url,
            published_at=row.published_at,
            accession=row.accession_number,
            document_type=row.document_type,
        )
        for row in session.scalars(
            select(FilingBuybackStatement).where(
                FilingBuybackStatement.entity_id.in_(chain),
                FilingBuybackStatement.published_at <= at,
                FilingBuybackStatement.extractor_version == extractor_version,
                recorded_by(FilingBuybackStatement.recorded_at, system_time),
            )
        )
    ]
    released = []
    for item in session.scalars(
        select(NewsItem)
        .join(NewsMention, NewsMention.news_item_id == NewsItem.id)
        .where(
            NewsMention.instrument_id == instrument.id,
            NewsItem.kind == "press_release",
            NewsItem.published_at <= at,
            recorded_by(NewsItem.recorded_at, system_time),
            recorded_by(NewsMention.recorded_at, system_time),
        )
        .distinct()
    ):
        for text in (item.title, item.snippet):
            found = statement(text) if text else None
            if found is not None:
                released.append(
                    AnnouncementSource(
                        channel="press_release",
                        kind=found.kind,
                        amount=found.amount,
                        remaining_amount=found.remaining_amount,
                        stated_date=found.stated_date,
                        sentence=found.sentence,
                        url=item.url,
                        published_at=item.published_at,
                        title=item.title,
                    )
                )
    return filed + released


def event_out(event: Event) -> AnnouncementEvent:
    return AnnouncementEvent(
        kind=event.kind,  # type: ignore[arg-type]
        amount=event.amount,
        remaining_amount=event.remaining_amount,
        day=event.day,
        first_published_at=event.first_published_at,
        sources=[
            AnnouncementSourceOut(
                channel=s.channel,
                sentence=s.sentence,
                url=s.url,
                published_at=s.published_at,
                stated_date=s.stated_date,
                accession=s.accession,
                document_type=s.document_type,
                title=s.title,
            )
            for s in event.sources
        ],
    )
