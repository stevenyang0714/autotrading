"""Insert-only access to prices (M0.7, ADR-017).

- market_quotes: one row per instrument and quote time; a repeated snapshot is ignored.
- price_bars: versioned with `apply_versions` (ADR-012/013): a re-based split-adjusted history
  becomes new versions with revision_reason `revision`.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.orm import Session, aliased

from autotrading.db.models import Identifier, MarketQuote, PriceBar
from autotrading.domain.market_calendar import NEW_YORK
from autotrading.domain.provenance import Provenance
from autotrading.repositories.audit import set_actor
from autotrading.repositories.facts import BatchResult, Incoming, apply_versions, as_of_query


@dataclass(frozen=True)
class BarIn:
    instrument_id: UUID
    symbol: str
    adjustment: str
    bar_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    vwap: Decimal | None
    trade_count: int | None
    feed: str
    feed_status: str  # end_of_day, or fixture for recorded test data
    provenance: Provenance

    def fact_key(self) -> tuple[Any, ...]:
        return (self.instrument_id, self.adjustment, self.bar_time)


def bar_key(row: PriceBar) -> tuple[Any, ...]:
    return (row.instrument_id, row.adjustment, row.bar_time)


class PriceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def insert_quotes(self, rows: Sequence[dict[str, Any]], *, actor: str) -> int:
        """Store snapshot rows; returns how many were new (same instrument and time: kept)."""
        if not rows:
            return 0
        set_actor(self.session, actor)
        result = self.session.execute(
            insert(MarketQuote)
            .on_conflict_do_nothing(index_elements=["instrument_id", "published_at"])
            .returning(MarketQuote.id),
            list(rows),
        )
        return len(result.all())

    def insert_bars(self, bars: Iterable[BarIn], *, actor: str) -> BatchResult:
        set_actor(self.session, actor)
        incoming = [
            Incoming(
                item=bar,
                key=bar.fact_key(),
                published_at=bar.provenance.published_at,
                value=bar.close,
                label=f"{bar.symbol} {bar.adjustment} {bar.bar_time.date()}",
            )
            for bar in bars
        ]
        if not incoming:
            return BatchResult(0, 0, [])
        times = [i.item.bar_time for i in incoming]
        existing = self.session.scalars(
            select(PriceBar)
            .where(
                PriceBar.instrument_id.in_({i.item.instrument_id for i in incoming}),
                PriceBar.adjustment.in_({i.item.adjustment for i in incoming}),
                PriceBar.bar_time.between(min(times), max(times)),
            )
            .order_by(PriceBar.published_at, PriceBar.recorded_at, PriceBar.id)
        )

        def build(bar: BarIn, version: int, latest: PriceBar | None) -> PriceBar:
            return PriceBar(
                id=uuid4(),
                instrument_id=bar.instrument_id,
                symbol=bar.symbol,
                adjustment=bar.adjustment,
                bar_time=bar.bar_time,
                bar_date=bar.bar_time.astimezone(NEW_YORK).date(),
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                vwap=bar.vwap,
                trade_count=bar.trade_count,
                feed=bar.feed,
                feed_status=bar.feed_status,
                **bar.provenance.model_dump(),
                version=version,
                supersedes_id=latest.id if latest is not None else None,
                revision_reason="revision" if latest is not None else None,
            )

        new_rows, result = apply_versions(existing, bar_key, incoming, build)
        self.session.add_all(new_rows)
        self.session.flush()
        return result

    def latest_quote_time(self) -> datetime | None:
        return self.session.scalar(select(func.max(MarketQuote.published_at)))


# ---------- reads ----------


def instruments_by_symbol(
    session: Session, symbols: Sequence[str] | None = None
) -> dict[str, UUID]:
    """Open alpaca ticker identifiers -> instrument ids (all universe symbols if None)."""
    query = select(Identifier.id_value, Identifier.instrument_id).where(
        Identifier.id_type == "ticker",
        Identifier.id_namespace == "alpaca",
        Identifier.valid_to.is_(None),
        Identifier.instrument_id.is_not(None),
    )
    if symbols is not None:
        query = query.where(Identifier.id_value.in_([s.upper() for s in symbols]))
    return {symbol: instrument for symbol, instrument in session.execute(query).all() if instrument}


def latest_quotes(
    session: Session, instrument_ids: Iterable[UUID], *, known_at: datetime | None = None
) -> dict[UUID, MarketQuote]:
    """Newest stored quote per instrument (at or before `known_at`)."""
    ids = list(instrument_ids)
    if not ids:
        return {}
    query = (
        select(MarketQuote)
        .where(MarketQuote.instrument_id.in_(ids))
        .ext(distinct_on(MarketQuote.instrument_id))
        .order_by(MarketQuote.instrument_id, MarketQuote.published_at.desc())
    )
    if known_at is not None:
        query = query.where(MarketQuote.published_at <= known_at)
    return {quote.instrument_id: quote for quote in session.scalars(query)}


def daily_bars(
    session: Session,
    instrument_id: UUID,
    adjustment: str,
    *,
    since: datetime,
    until: datetime,
    known_at: datetime,
    system_time: datetime | None = None,
) -> list[PriceBar]:
    """Daily bars between two times, each as known at `known_at` and as this database held
    them at `system_time` (default: now; ADR-012), oldest first."""
    known = as_of_query(PriceBar, known_at=known_at, system_time=system_time).where(
        PriceBar.instrument_id == instrument_id,
        PriceBar.adjustment == adjustment,
        PriceBar.bar_time >= since,
        PriceBar.bar_time <= until,
    )
    row = aliased(PriceBar, known.subquery())
    return list(session.scalars(select(row).order_by(row.bar_time)))
