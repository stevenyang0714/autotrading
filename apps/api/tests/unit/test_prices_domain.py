"""domain/prices: feed status rules (errata E4), day change, 52-week high, PIT rebasing."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from fractions import Fraction

import pytest

from autotrading.domain.market_calendar import MarketCalendar
from autotrading.domain.prices import (
    QUOTE_SLA,
    Bar,
    below_high_percent,
    change_percent,
    quote_feed_status,
    rebase_split_adjusted,
    split_factor,
)

CAL = MarketCalendar(
    holidays=frozenset(), early_closes=frozenset(), covered_until=date(2028, 12, 31)
)
OPEN = datetime(2026, 10, 5, 16, 0, tzinfo=UTC)  # Monday 12:00 ET
CLOSED = datetime(2026, 10, 5, 23, 0, tzinfo=UTC)  # Monday 19:00 ET
CLOSE = datetime(2026, 10, 5, 20, 0, tzinfo=UTC)


def status(published: datetime | None, now: datetime, **kw: object) -> str:
    args: dict[str, object] = {"stored_status": "live_single_venue", "provider_configured": True}
    args.update(kw)
    return quote_feed_status(published_at=published, now=now, calendar=CAL, **args)  # type: ignore[arg-type]


def test_fresh_quote_in_session_is_live_single_venue() -> None:
    assert status(OPEN - timedelta(seconds=30), OPEN) == "live_single_venue"


def test_quote_older_than_its_sla_renders_stale() -> None:
    # M0.7 acceptance: a quote older than its SLA renders `stale`.
    assert status(OPEN - QUOTE_SLA - timedelta(seconds=1), OPEN) == "stale"


def test_after_the_close_the_closing_quote_is_end_of_day() -> None:
    assert status(CLOSE - timedelta(seconds=10), CLOSED) == "end_of_day"
    assert status(CLOSE - timedelta(hours=2), CLOSED) == "stale"  # missed the close


@pytest.mark.parametrize(
    ("kw", "published", "expected"),
    [
        ({"provider_configured": False}, OPEN, "unavailable"),
        ({}, None, "unavailable"),
        ({"stored_status": "fixture"}, OPEN - timedelta(days=3), "fixture"),
        # Recorded data is shown as what it is even without a provider key (ADR-006).
        (
            {"stored_status": "fixture", "provider_configured": False},
            OPEN - timedelta(days=3),
            "fixture",
        ),
    ],
)
def test_unavailable_and_fixture(
    kw: dict[str, object], published: datetime | None, expected: str
) -> None:
    assert status(published, OPEN, **kw) == expected


def test_day_change_and_distance_from_the_high() -> None:
    assert change_percent(Decimal("774.74"), Decimal("769.65")) == Decimal("0.66")
    bars = [Bar(date(2026, 9, 1), Decimal(700)), Bar(date(2026, 9, 2), Decimal(800))]
    assert below_high_percent(bars, Decimal(760)) == (Decimal(800), Decimal("5.00"))
    assert below_high_percent(bars, Decimal(820)) == (Decimal(820), Decimal("0.00"))


def test_split_adjusted_history_is_rebased_to_the_as_of_day() -> None:
    # NVDA 10-for-1 on 2024-06-10: raw 1208.88 on 06-07, adjusted (today's basis) 120.89.
    raw = [Bar(date(2024, 6, 7), Decimal("1208.88")), Bar(date(2024, 6, 10), Decimal("121.79"))]
    adjusted = [Bar(date(2024, 6, 7), Decimal("120.89")), Bar(date(2024, 6, 10), Decimal("121.79"))]
    before_split = rebase_split_adjusted(adjusted, raw, date(2024, 6, 7))
    assert [b.close for b in before_split] == [Decimal("1208.8800")]  # as shown on 06-07
    after_split = rebase_split_adjusted(adjusted, raw, date(2024, 6, 10))
    # 1208.88 / 10 exactly (the provider rounds it to 120.89).
    assert [b.close for b in after_split] == [Decimal("120.8880"), Decimal("121.7900")]


def test_rebased_days_without_a_later_split_equal_their_raw_close() -> None:
    # NVDA as known on 06-06: 1209.98 / 121.00 is 9.99983, not 10; snapping to the split ratio
    # keeps 06-03 at its real close of 1150 instead of 1149.981.
    raw = [Bar(date(2024, 6, 3), Decimal("1150")), Bar(date(2024, 6, 6), Decimal("1209.98"))]
    adjusted = [Bar(date(2024, 6, 3), Decimal("115")), Bar(date(2024, 6, 6), Decimal("121"))]
    rebased = rebase_split_adjusted(adjusted, raw, date(2024, 6, 6))
    assert [b.close for b in rebased] == [Decimal("1150.0000"), Decimal("1209.9800")]


def test_split_factor_snaps_to_split_ratios() -> None:
    assert split_factor(Decimal("1209.98"), Decimal("121")) == Fraction(10)
    assert split_factor(Decimal("289.99"), Decimal("145")) == Fraction(2)
    assert split_factor(Decimal("774.83"), Decimal("774.83")) == Fraction(1)
    assert split_factor(Decimal("1.50"), Decimal("22.50")) == Fraction(1, 15)  # reverse 1:15
