"""Quarterly values and trailing twelve months (M1.1, ADR-021). Pure functions; no I/O.

10-Qs report flows year to date (cash flows only so). Quarters are therefore differenced from
the year-to-date values of one fiscal year, each with the provenance of both inputs:
    Q1 = 3 months; Q2 = 6 months - 3 months; Q3 = 9 months - 6 months; Q4 = year - 9 months.
A fiscal year starts on the start of a year-long period or the day after one ends (the year in
progress). Year-to-date lengths are told apart by days, which also covers 52/53-week years
(a 14-week quarter). Any missing input leaves that quarter unavailable.

EPS and weighted diluted shares do not difference (share counts change within the year): their
quarters are only the three-month values the company reports, and Q4 is never derived.
Trailing twelve months = the sum of the four latest consecutive quarters, flows only.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise

from autotrading.domain.derived import ValueFact
from autotrading.domain.fundamentals import FISCAL_YEAR_DAYS

# Days from start to end of a year-to-date period (end - start), by quarters covered: 13-week
# quarters (90/181/272 days), a 14-week quarter, and AutoZone's 12/12/12/16-week year
# (83/167/251 days). The ranges do not overlap.
YTD_DAYS = {1: range(80, 101), 2: range(160, 197), 3: range(245, 288)}
NON_ADDITIVE = frozenset({"eps_diluted", "diluted_shares", "eps_basic", "basic_shares"})
TTM_QUARTERS = 4


@dataclass(frozen=True)
class Quarter[FactT: ValueFact]:
    metric_id: str
    number: int  # 1-4 within the fiscal year
    fiscal_year_end: date | None  # None while the year is in progress
    period_start: date
    period_end: date
    value: Decimal
    method: str  # "reported" | "ytd_difference" | "year_minus_9_months"
    inputs: tuple[FactT, ...]  # the fact(s) the value comes from


def _days(fact: ValueFact) -> int:
    assert fact.period_start is not None
    return (fact.period_end - fact.period_start).days


def _ytd_quarters(fact: ValueFact) -> int | None:
    days = _days(fact)
    return next((n for n, span in YTD_DAYS.items() if days in span), None)


def quarters[FactT: ValueFact](facts: Iterable[FactT], metric_id: str) -> list[Quarter[FactT]]:
    """Quarters of one metric, oldest first."""
    durations = [f for f in facts if f.metric_id == metric_id and f.period_start is not None]
    years: dict[date, FactT] = {
        f.period_start: f for f in durations if f.period_start and _days(f) in FISCAL_YEAR_DAYS
    }
    anchors: set[date] = set(years) | {f.period_end + timedelta(days=1) for f in years.values()}
    ytd: dict[date, dict[int, FactT]] = defaultdict(dict)
    for fact in durations:
        if fact.period_start in anchors and (n := _ytd_quarters(fact)) is not None:
            assert fact.period_start is not None
            ytd[fact.period_start][n] = fact
    three_months = {(f.period_start, f.period_end): f for f in durations if _ytd_quarters(f) == 1}
    out: list[Quarter[FactT]] = []
    for start in sorted(anchors):
        year, parts = years.get(start), ytd.get(start, {})
        fiscal_end = year.period_end if year else None
        ends = [parts[n].period_end if n in parts else None for n in (1, 2, 3)]
        bounds = [start, *[(e + timedelta(days=1)) if e else None for e in ends]]
        for number in (1, 2, 3, 4):
            q_start = bounds[number - 1]
            q_end = ends[number - 1] if number < 4 else fiscal_end
            if q_start is None or q_end is None:
                continue
            if metric_id in NON_ADDITIVE:
                reported = three_months.get((q_start, q_end))
                if number < 4 and reported is not None:
                    out.append(
                        Quarter(
                            metric_id,
                            number,
                            fiscal_end,
                            q_start,
                            q_end,
                            reported.value,
                            "reported",
                            (reported,),
                        )
                    )
                continue
            if number == 1:
                out.append(
                    Quarter(
                        metric_id,
                        1,
                        fiscal_end,
                        q_start,
                        q_end,
                        parts[1].value,
                        "reported",
                        (parts[1],),
                    )
                )
                continue
            later = parts.get(number) if number < 4 else year
            earlier = parts.get(number - 1)
            if later is None or earlier is None:
                continue
            method = "ytd_difference" if number < 4 else "year_minus_9_months"
            out.append(
                Quarter(
                    metric_id,
                    number,
                    fiscal_end,
                    q_start,
                    q_end,
                    later.value - earlier.value,
                    method,
                    (later, earlier),
                )
            )
    return sorted(out, key=lambda q: q.period_end)


def trailing_twelve_months[FactT: ValueFact](
    series: list[Quarter[FactT]],
) -> tuple[Decimal, list[Quarter[FactT]]] | None:
    """Sum of the latest four consecutive quarters of a flow; None if they are not all there."""
    if not series or series[0].metric_id in NON_ADDITIVE or len(series) < TTM_QUARTERS:
        return None
    last = series[-TTM_QUARTERS:]
    for before, after in pairwise(last):
        if after.period_start != before.period_end + timedelta(days=1):
            return None
    return sum((q.value for q in last), Decimal(0)), last
