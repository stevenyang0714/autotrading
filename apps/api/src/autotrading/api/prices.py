"""Prices API (M0.7, ADR-017): latest quotes with their feed status, and an instrument's
daily price history as known at a time.

Every quote carries the feed_status the UI must show next to it (errata E4). Without a
configured provider, or with nothing stored, the status is `unavailable` and no number is sent.
Recorded test data is always shown, labelled `fixture` (ADR-006: the UI adds a DEMO DATA banner).
Past points in time use daily closes only (raw bars, public at the end of their New York day);
the chart is the split-adjusted series re-based to that day, so later splits do not leak in.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, NamedTuple
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import AwareDatetime, BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from autotrading.adapters.alpaca.provider import AlpacaProvider
from autotrading.api.data_health import SessionDep
from autotrading.db.models import MarketQuote, PriceBar, Source
from autotrading.domain.market_calendar import MarketCalendar
from autotrading.domain.prices import (
    Bar,
    FeedStatus,
    PriceProvider,
    below_high_percent,
    change_percent,
    quote_feed_status,
    rebase_split_adjusted,
)
from autotrading.ingestion.schedule import market_calendar
from autotrading.repositories.prices import (
    daily_bars,
    instruments_by_symbol,
    latest_quotes,
)

router = APIRouter(tags=["prices"])

# The active price provider (ADR-004): Alpaca now; Massive once licensed.
PRICE_PROVIDER: PriceProvider = AlpacaProvider()
ONE_YEAR = timedelta(days=366)
FAR_FUTURE = datetime(9999, 12, 31, tzinfo=UTC)


class MarketState(BaseModel):
    open: bool
    last_close: datetime
    next_open: datetime
    calendar_covered_until: date


class QuoteOut(BaseModel):
    symbol: str
    feed_status: FeedStatus
    # None whenever feed_status is unavailable: no number without a source.
    last: Decimal | None = None
    prev_close: Decimal | None = None
    change_pct: Decimal | None = None
    bid: Decimal | None = None
    ask: Decimal | None = None
    day_volume: int | None = None
    venue: str | None = None
    published_at: datetime | None = None
    received_at: datetime | None = None


class LatestPrices(BaseModel):
    as_of: datetime
    provider_configured: bool
    market: MarketState
    quotes: list[QuoteOut]


class ClosePoint(BaseModel):
    day: date
    close: Decimal


class InstrumentPrices(BaseModel):
    ticker: str
    known_at: datetime
    provider_configured: bool
    market: MarketState
    quote: QuoteOut | None  # live view only (no known_at)
    # Daily closes: end_of_day, fixture (recorded test data) or unavailable (nothing shown).
    closes_feed_status: FeedStatus
    last_close: ClosePoint | None  # the latest daily close known at known_at (raw)
    previous_close: ClosePoint | None  # the close before it, on the same split basis
    close_change_pct: Decimal | None  # last_close against previous_close
    history: list[ClosePoint]  # one year of split-adjusted closes on known_at's basis
    high_52w: Decimal | None
    pct_below_52w_high: Decimal | None


class History(NamedTuple):
    feed_status: FeedStatus
    last_close: ClosePoint | None
    previous_close: ClosePoint | None
    closes: list[ClosePoint]
    high_52w: Decimal | None
    pct_below_52w_high: Decimal | None


def provider_ready(session: Session) -> bool:
    source = session.get(Source, PRICE_PROVIDER.source_id)
    return source is not None and source.enabled and PRICE_PROVIDER.configured()


def market_state(calendar: MarketCalendar, now: datetime) -> MarketState:
    return MarketState(
        open=calendar.is_open(now),
        last_close=calendar.last_close(now),
        next_open=calendar.next_open(now),
        calendar_covered_until=calendar.covered_until,
    )


def quote_out(
    symbol: str, quote: MarketQuote | None, *, now: datetime, calendar: MarketCalendar, ready: bool
) -> QuoteOut:
    status = quote_feed_status(
        stored_status=quote.feed_status if quote else None,
        published_at=quote.published_at if quote else None,
        now=now,
        calendar=calendar,
        provider_configured=ready,
    )
    if status == "unavailable" or quote is None:
        return QuoteOut(symbol=symbol, feed_status="unavailable")
    last = quote.last
    return QuoteOut(
        symbol=symbol,
        feed_status=status,
        last=last,
        prev_close=quote.prev_close,
        change_pct=change_percent(last, quote.prev_close) if last and quote.prev_close else None,
        bid=quote.bid,
        ask=quote.ask,
        day_volume=quote.day_volume,
        venue=quote.venue,
        published_at=quote.published_at,
        received_at=quote.received_at,
    )


@router.get("/prices/latest")
def prices_latest(
    session: SessionDep,
    symbols: Annotated[str | None, Query(description="Comma-separated; default all")] = None,
) -> LatestPrices:
    now: datetime = session.execute(select(func.now())).scalar_one()
    calendar = market_calendar()
    ready = provider_ready(session)
    wanted = [s.strip().upper() for s in symbols.split(",")] if symbols else None
    instruments = instruments_by_symbol(session, wanted)
    quotes = latest_quotes(session, instruments.values())
    names = wanted or sorted(instruments)
    return LatestPrices(
        as_of=now,
        provider_configured=ready,
        market=market_state(calendar, now),
        quotes=[
            quote_out(
                symbol,
                quotes.get(instruments[symbol]) if symbol in instruments else None,
                now=now,
                calendar=calendar,
                ready=ready,
            )
            for symbol in names
        ],
    )


def shown(bars: list[PriceBar], ready: bool) -> list[PriceBar]:
    """Bars the UI may show: all with a configured provider, else recorded fixtures only."""
    return bars if ready else [bar for bar in bars if bar.feed_status == "fixture"]


def price_history(
    session: Session,
    instrument_id: UUID,
    *,
    known_at: datetime,
    last: Decimal | None,
    ready: bool,
    since: datetime | None = None,
) -> History:
    """Latest raw closes, one year of re-based closes and the 52-week high, as known at
    known_at. `last` (a live price) counts towards the high when given."""
    since = since or known_at - ONE_YEAR
    raw = shown(
        daily_bars(session, instrument_id, "raw", since=since, until=known_at, known_at=known_at),
        ready,
    )
    # The split-adjusted series is read on today's basis (as known now); re-basing it to
    # known_at's factor removes splits that happened later.
    adjusted = shown(
        daily_bars(
            session, instrument_id, "split", since=since, until=known_at, known_at=FAR_FUTURE
        ),
        ready,
    )
    if not raw:
        return History("unavailable", None, None, [], None, None)
    # Only days whose close was public at known_at: a raw bar counts from the end of its New
    # York day, so the chart stops at the latest raw close known then.
    as_of_day = raw[-1].bar_date
    history = rebase_split_adjusted(
        [Bar(b.bar_date, b.close) for b in adjusted if b.bar_date <= as_of_day],
        [Bar(b.bar_date, b.close) for b in raw],
        as_of_day,
    )
    status: FeedStatus = (
        "fixture" if any(b.feed_status == "fixture" for b in raw + adjusted) else "end_of_day"
    )
    last_close = ClosePoint(day=raw[-1].bar_date, close=raw[-1].close)
    # The previous close on the same basis as the last one: across a split, raw closes differ
    # by the split ratio, so it comes from the re-based series (none if that day is missing).
    rebased = {bar.day: bar.close for bar in history}
    previous_day = raw[-2].bar_date if len(raw) > 1 else None
    previous = (
        ClosePoint(day=previous_day, close=rebased[previous_day])
        if previous_day in rebased
        else None
    )
    high = below_high_percent(history, last if last is not None else last_close.close)
    return History(
        status,
        last_close,
        previous,
        [ClosePoint(day=b.day, close=b.close) for b in history],
        high[0] if high else None,
        high[1] if high else None,
    )


@router.get("/instruments/{ticker}/prices")
def instrument_prices(
    ticker: str,
    session: SessionDep,
    known_at: Annotated[
        AwareDatetime | None, Query(description="Point in time (ADR-012); default now")
    ] = None,
) -> InstrumentPrices:
    symbol = ticker.upper()
    instrument = instruments_by_symbol(session, [symbol]).get(symbol)
    if instrument is None:
        raise HTTPException(status_code=404, detail=f"no prices for {ticker!r}")
    now: datetime = session.execute(select(func.now())).scalar_one()
    at = known_at or now
    calendar = market_calendar()
    ready = provider_ready(session)
    quote = None
    if known_at is None:
        stored = latest_quotes(session, [instrument]).get(instrument)
        quote = quote_out(symbol, stored, now=now, calendar=calendar, ready=ready)
    history = price_history(
        session, instrument, known_at=at, last=quote.last if quote else None, ready=ready
    )
    return InstrumentPrices(
        ticker=symbol,
        known_at=at,
        provider_configured=ready,
        market=market_state(calendar, now),
        quote=quote,
        closes_feed_status=history.feed_status,
        last_close=history.last_close,
        previous_close=history.previous_close,
        close_change_pct=(
            change_percent(history.last_close.close, history.previous_close.close)
            if history.last_close and history.previous_close
            else None
        ),
        history=history.closes,
        high_52w=history.high_52w,
        pct_below_52w_high=history.pct_below_52w_high,
    )
