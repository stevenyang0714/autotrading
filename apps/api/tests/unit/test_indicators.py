"""domain/indicators: computed macro indicators on fixed series."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from autotrading.domain.indicators import (
    Point,
    annualized_growth,
    annualized_growth_series,
    band,
    inversion_streak,
    latest_change,
    percentile_rank,
    relation_to_target,
    revision,
    sahm_indicator,
    yoy_percent,
    yoy_series,
)


def monthly(values: list[str], start: date = date(2025, 1, 1)) -> list[Point]:
    out = []
    for i, value in enumerate(values):
        month = start.month - 1 + i
        out.append(Point(date(start.year + month // 12, month % 12 + 1, 1), Decimal(value)))
    return out


def test_yoy_compares_with_the_same_month_a_year_earlier() -> None:
    points = monthly(["100"] + ["101"] * 11 + ["103"])  # Jan 2025 .. Jan 2026
    assert yoy_percent(points) == Decimal("3.00")
    assert yoy_percent(points[:-1]) is None  # Dec 2025 has no Dec 2024
    assert [p.day for p in yoy_series(points)] == [date(2026, 1, 1)]


def test_monthly_change_and_revision() -> None:
    assert latest_change(monthly(["159015", "159044"])) == Decimal(29)
    assert latest_change(monthly(["1"])) is None
    assert revision(Decimal(159015), Decimal(159075)) == Decimal(-60)


def test_sahm_indicator_uses_three_month_averages() -> None:
    flat = monthly(["4.0"] * 15)
    assert sahm_indicator(flat) == Decimal("0.00")
    rising = monthly(["4.0"] * 12 + ["4.5", "4.6", "4.7"])
    # current 3-month average 4.60, lowest of the previous twelve 4.00
    assert sahm_indicator(rising) == Decimal("0.60")
    assert sahm_indicator(rising[:14]) is None


def test_annualized_growth() -> None:
    points = [
        Point(date(2026, 1, 1), Decimal("24274.383")),
        Point(date(2026, 4, 1), Decimal("24408.011")),
    ]
    assert annualized_growth(points) == Decimal("2.22")
    assert [p.value for p in annualized_growth_series(points)] == [Decimal("2.22")]


def test_inversion_streak_counts_back_to_the_last_sign_change() -> None:
    start = date(2026, 9, 1)
    values = ["-0.10", "-0.05", "0.02", "0.10", "0.45"]
    points = [Point(start + timedelta(days=i), Decimal(v)) for i, v in enumerate(values)]
    streak = inversion_streak(points)
    assert streak is not None
    assert (streak.inverted, streak.observations, streak.since) == (False, 3, date(2026, 9, 3))
    inverted = inversion_streak(points[:2])
    assert inverted is not None and inverted.inverted and inverted.observations == 2


def test_percentile_rank_and_bands() -> None:
    points = [Point(date(2026, 1, i), Decimal(v)) for i, v in enumerate([5, 1, 3, 2, 4], start=1)]
    assert percentile_rank(points) == Decimal("80.00")  # 1, 2, 3 and 4 are at or below 4
    assert [band(Decimal(x)) for x in (10, 50, 90)] == ["low", "mid-range", "high"]


@pytest.mark.parametrize(
    ("value", "relation"), [("2.94", "above"), ("1.96", "at"), ("1.80", "below")]
)
def test_relation_to_the_fed_target(value: str, relation: str) -> None:
    assert relation_to_target(Decimal(value)) == relation
