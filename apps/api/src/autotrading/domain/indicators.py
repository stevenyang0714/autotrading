"""Computed macro indicators and their rule-based labels (M0.6 overview, ADR-016).

Pure functions over observations already filtered to one point in time (`as_of`, ADR-012),
oldest first. Each indicator has a glossary term with the same id and is registered in
domain/metrics.py; thresholds used for labels live here and in the glossary text.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

FED_INFLATION_TARGET = Decimal("2.0")  # percent, PCE inflation (FOMC statement of goals)
SAHM_TRIGGER = Decimal("0.50")  # percentage points
LOW_PERCENTILE, HIGH_PERCENTILE = Decimal(25), Decimal(75)

TWO = Decimal("0.01")
Relation = Literal["above", "below", "at"]
Band = Literal["low", "mid-range", "high"]


@dataclass(frozen=True)
class Point:
    day: date
    value: Decimal


def _round(value: Decimal) -> Decimal:
    return value.quantize(TWO, rounding=ROUND_HALF_UP)


def _months_back(day: date, months: int) -> date:
    month = day.month - 1 - months
    return date(day.year + month // 12, month % 12 + 1, 1)


def yoy_percent(points: Sequence[Point]) -> Decimal | None:
    """Change of the latest monthly value against the same month a year earlier, in %."""
    if not points:
        return None
    latest = points[-1]
    year_ago = _months_back(latest.day, 12)
    base = next((p for p in points if p.day == year_ago), None)
    if base is None or base.value == 0:
        return None
    return _round((latest.value / base.value - 1) * 100)


def yoy_series(points: Sequence[Point]) -> list[Point]:
    """`yoy_percent` at every month that has a value twelve months earlier."""
    by_day = {p.day: p.value for p in points}
    out = []
    for point in points:
        base = by_day.get(_months_back(point.day, 12))
        if base:
            out.append(Point(point.day, _round((point.value / base - 1) * 100)))
    return out


def latest_change(points: Sequence[Point]) -> Decimal | None:
    """Latest value minus the one before (e.g. the monthly change in payrolls)."""
    if len(points) < 2:
        return None
    return points[-1].value - points[-2].value


def revision(current: Decimal, first_release: Decimal) -> Decimal:
    """How far a value moved from its first release (positive = revised up)."""
    return current - first_release


def sahm_indicator(points: Sequence[Point]) -> Decimal | None:
    """Sahm rule: 3-month average unemployment rate minus the lowest 3-month average of the
    previous 12 months, in percentage points. 0.50 or more has marked US recessions."""
    if len(points) < 15:
        return None
    averages = [
        sum((p.value for p in points[i - 2 : i + 1]), Decimal(0)) / 3 for i in range(2, len(points))
    ]
    current, previous = averages[-1], averages[-13:-1]
    return _round(current - min(previous))


def annualized_growth(points: Sequence[Point]) -> Decimal | None:
    """Quarter-on-quarter growth expressed at an annual rate, in %."""
    if len(points) < 2 or points[-2].value == 0:
        return None
    ratio = float(points[-1].value / points[-2].value)
    return _round(Decimal(str((ratio**4 - 1) * 100)))


def annualized_growth_series(points: Sequence[Point]) -> list[Point]:
    return [
        Point(points[i].day, growth)
        for i in range(1, len(points))
        if (growth := annualized_growth(points[i - 1 : i + 1])) is not None
    ]


@dataclass(frozen=True)
class Streak:
    inverted: bool
    observations: int  # consecutive observations in the current state, latest included
    since: date


def inversion_streak(points: Sequence[Point]) -> Streak | None:
    """Whether the latest spread is below zero, and since when it has been on that side."""
    if not points:
        return None
    inverted = points[-1].value < 0
    count, since = 0, points[-1].day
    for point in reversed(points):
        if (point.value < 0) != inverted:
            break
        count, since = count + 1, point.day
    return Streak(inverted, count, since)


def percentile_rank(points: Sequence[Point]) -> Decimal | None:
    """Share of observations at or below the latest one, in % (0-100)."""
    if not points:
        return None
    latest = points[-1].value
    at_or_below = sum(1 for p in points if p.value <= latest)
    return _round(Decimal(at_or_below * 100) / len(points))


def relation_to_target(value: Decimal, target: Decimal = FED_INFLATION_TARGET) -> Relation:
    rounded = value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if rounded > target:
        return "above"
    return "below" if rounded < target else "at"


def band(percentile: Decimal) -> Band:
    if percentile < LOW_PERCENTILE:
        return "low"
    return "high" if percentile > HIGH_PERCENTILE else "mid-range"
