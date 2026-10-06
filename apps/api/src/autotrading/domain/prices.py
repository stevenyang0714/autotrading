"""Prices (M0.7, ADR-017): the PriceProvider contract, feed status rules (errata E4) and
price calculations. Pure; storage and HTTP live in adapters/alpaca and repositories.

feed_status of a quote shown to the user:
- fixture: the quote came from recorded test data (a DEMO DATA banner is shown), with or
  without a provider key: it is labelled as what it is;
- unavailable: no provider configured, or nothing stored (no number is shown);
- live_single_venue: market open and the quote is at most QUOTE_SLA old (IEX only);
- stale: market open and the quote is older than QUOTE_SLA, or the market is closed and the
  newest quote predates the last close;
- end_of_day: market closed and the newest quote is from the last session's close.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import ClassVar, Literal, Protocol

from autotrading.domain.market_calendar import MarketCalendar

FeedStatus = Literal[
    "live_consolidated",
    "live_single_venue",
    "delayed",
    "end_of_day",
    "stale",
    "unavailable",
    "fixture",
    "demo",
]
Adjustment = Literal["raw", "split"]

# A quote older than this while the market is open is stale. We poll every 60 seconds.
QUOTE_SLA = timedelta(seconds=120)
# The last poll runs a minute after the close; a quote this close to the close counts as final.
CLOSE_GRACE = timedelta(minutes=5)


def quote_feed_status(
    *,
    stored_status: str | None,
    published_at: datetime | None,
    now: datetime,
    calendar: MarketCalendar,
    provider_configured: bool,
) -> FeedStatus:
    """What the UI badge says for the newest stored quote of an instrument."""
    if published_at is None:
        return "unavailable"
    if stored_status == "fixture":
        return "fixture"
    if not provider_configured:
        return "unavailable"
    if calendar.is_open(now):
        return "live_single_venue" if now - published_at <= QUOTE_SLA else "stale"
    last_close = calendar.last_close(now)
    return "end_of_day" if published_at >= last_close - CLOSE_GRACE else "stale"


def _round(value: Decimal, places: str = "0.01") -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def change_percent(last: Decimal, previous: Decimal) -> Decimal | None:
    """Percent change from `previous` to `last` (the day change: last vs previous close)."""
    if previous == 0:
        return None
    return _round((last / previous - 1) * 100)


@dataclass(frozen=True)
class Bar:
    day: date
    close: Decimal


def below_high_percent(bars: Sequence[Bar], last: Decimal) -> tuple[Decimal, Decimal] | None:
    """(highest close of the window, percent the last price sits below it, >= 0)."""
    if not bars:
        return None
    high = max(max(bar.close for bar in bars), last)
    if high == 0:
        return None
    return high, _round((1 - last / high) * 100)


# Split ratios are small fractions (2:1, 3:2, 1:15); a ratio of two closes rounded to cents is
# not exactly one, so it is snapped to the nearest such fraction when that is this close.
SPLIT_MAX_DENOMINATOR = 50
SPLIT_SNAP_TOLERANCE = Fraction(1, 200)  # 0.5%


def split_factor(raw: Decimal, adjusted: Decimal) -> Fraction:
    """Product of the split ratios after a day (raw / split-adjusted close), as an exact
    fraction: 1 without a later split, 10 before NVDA's 10-for-1."""
    ratio = Fraction(raw) / Fraction(adjusted)
    snapped = ratio.limit_denominator(SPLIT_MAX_DENOMINATOR)
    return snapped if abs(snapped / ratio - 1) <= SPLIT_SNAP_TOLERANCE else ratio


def rebase_split_adjusted(
    adjusted: Sequence[Bar], raw: Sequence[Bar], as_of_day: date
) -> list[Bar]:
    """Split-adjusted closes as they would have been shown on `as_of_day` (no look-ahead).

    The provider's split-adjusted series reflects every split up to today. On `as_of_day`'s
    basis a day's close is its raw close divided by the splits between that day and
    `as_of_day` only: raw x factor(as_of_day) / factor(day). A day with no split since shows
    exactly its raw close; a day without a raw close falls back to its adjusted close.
    """
    raw_by_day = {bar.day: bar.close for bar in raw}
    window = [bar for bar in adjusted if bar.day <= as_of_day]
    anchor = next((bar for bar in reversed(window) if raw_by_day.get(bar.day) and bar.close), None)
    if anchor is None:
        return list(window)
    later = split_factor(raw_by_day[anchor.day], anchor.close)  # splits after as_of_day
    rebased = []
    for bar in window:
        own = raw_by_day.get(bar.day)
        if own and bar.close:
            value = Fraction(own) * later / split_factor(own, bar.close)
        else:
            value = Fraction(bar.close) * later
        rebased.append(Bar(bar.day, _round(Decimal(value.numerator) / value.denominator, "0.0001")))
    return rebased


class PriceProvider(Protocol):
    """A market data provider behind one interface (ADR-004): Alpaca first, Massive later."""

    source_id: ClassVar[str]
    live_feed_status: ClassVar[FeedStatus]  # what a fresh quote from this provider is labelled

    def configured(self) -> bool:
        """Credentials present and the provider allowed to run (license checks recorded)."""
        ...
