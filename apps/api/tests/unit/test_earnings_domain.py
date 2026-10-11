"""Earnings events (M1.5, ADR-026): timing, reaction against SPY, the report and its actuals."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import yaml

from autotrading.domain.earnings import (
    Actual,
    DayBar,
    Report,
    actuals,
    match_report,
    reaction,
    session_close,
    timing,
)
from autotrading.domain.market_calendar import NEW_YORK, load_calendar
from autotrading.domain.provenance import end_of_day
from autotrading.domain.splits import Split

CALENDAR = load_calendar(
    yaml.safe_load(
        (Path(__file__).resolve().parents[4] / "config" / "market_calendar.yaml").read_text()
    )
)


def ny(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=NEW_YORK)


def d(text: str) -> date:
    return date.fromisoformat(text)


def sessions(start: str, count: int) -> list[date]:
    out: list[date] = []
    day = d(start)
    while len(out) < count:
        if CALENDAR.session(day) is not None:
            out.append(day)
        day += timedelta(days=1)
    return out


def bars(days: list[date], closes: list[str], volume: int = 100) -> list[DayBar]:
    return [
        DayBar(day, Decimal(c), volume, "end_of_day", end_of_day(day))
        for day, c in zip(days, closes, strict=True)
    ]


# Apple: the 8-K of 2026-04-30 was accepted at 16:30:41, after the close.
APPLE_EVENT = ny("2026-04-30T16:30:41")
DAYS = sessions("2026-03-31", 30)  # 2026-03-31 ... into May
BASE = DAYS.index(d("2026-04-30"))


def apple(closes_after: list[str], volume_day0: int = 300) -> list[DayBar]:
    before = bars(DAYS[: BASE + 1], ["100"] * (BASE + 1))
    after = bars(DAYS[BASE + 1 : BASE + 1 + len(closes_after)], closes_after, volume_day0)
    return before + after


def spy(closes_after: list[str]) -> list[DayBar]:
    return bars(DAYS[: BASE + 1], ["500"] * (BASE + 1)) + bars(
        DAYS[BASE + 1 : BASE + 1 + len(closes_after)], closes_after
    )


def test_timing_by_the_new_york_session() -> None:
    known = frozenset(DAYS)
    assert timing(APPLE_EVENT, CALENDAR, known) == "after_hours"
    assert timing(ny("2026-04-30T06:31:49"), CALENDAR, known) == "pre_market"  # like XOM
    assert timing(ny("2026-04-30T11:00:00"), CALENDAR, known) == "market_hours"
    assert timing(ny("2026-05-02T09:00:00"), CALENDAR, known) == "non_session"  # a Saturday
    assert session_close(d("2026-11-27"), CALENDAR) == ny("2026-11-27T13:00:00")  # early close


def test_an_after_hours_release_reacts_from_the_next_close() -> None:
    # Acceptance 2: the close of the event day is the base, never day 0.
    stock = apple(["104", "106", "100", "100", "100", "108"])
    bench = spy(["505", "505", "500", "500", "500", "510"])
    found = reaction(APPLE_EVENT, stock, bench, ny("2026-05-11T20:00:00"), CALENDAR, [])
    assert found.base_day == d("2026-04-30")
    assert [
        (w.label, w.day, w.stock_return, w.benchmark_return, w.relative) for w in found.windows
    ] == [
        ("day 0", d("2026-05-01"), Decimal("4.00"), Decimal("1.00"), Decimal("3.00")),
        ("day +1", d("2026-05-04"), Decimal("6.00"), Decimal("1.00"), Decimal("5.00")),
        ("day +5", d("2026-05-08"), Decimal("8.00"), Decimal("2.00"), Decimal("6.00")),
    ]
    assert found.volume_ratio == Decimal("3.00")  # 300 against 20 sessions of 100


def test_nothing_after_the_event_is_known_before_the_next_close() -> None:
    stock = apple(["104", "106", "100", "100", "100", "108"])
    evening = reaction(
        APPLE_EVENT, stock, spy(["505"] * 6), ny("2026-05-01T01:00:00"), CALENDAR, []
    )
    assert evening.base_day == d("2026-04-30")
    assert [(w.day, w.detail) for w in evening.windows] == [
        (None, "no end-of-day close yet"),
        (None, "no end-of-day close yet"),
        (None, "no end-of-day close yet"),
    ]
    assert evening.volume_ratio is None
    # Two closes later (each public at the end of its day), day +5 is still unknown.
    later = reaction(APPLE_EVENT, stock, spy(["505"] * 6), ny("2026-05-05T01:00:00"), CALENDAR, [])
    assert [w.day for w in later.windows] == [d("2026-05-01"), d("2026-05-04"), None]


def test_a_pre_market_release_reacts_the_same_day() -> None:
    event = ny("2026-04-30T06:31:49")
    stock = bars(DAYS[: BASE + 2], ["100"] * BASE + ["110", "111"])
    found = reaction(event, stock, spy(["500"]), ny("2026-05-01T20:00:00"), CALENDAR, [])
    assert found.base_day == DAYS[BASE - 1]  # 2026-04-29
    assert (found.windows[0].day, found.windows[0].stock_return) == (
        d("2026-04-30"),
        Decimal("10.00"),
    )


def test_fixture_closes_and_splits() -> None:
    fixture = [DayBar(b.day, b.close, b.volume, "fixture", b.published_at) for b in apple(["104"])]
    assert reaction(
        APPLE_EVENT, fixture, spy(["505"]), ny("2026-05-11T20:00:00"), CALENDAR, []
    ).detail == ("no end-of-day close in the week before the event")
    # A 4-for-1 split effective on day 0: the base close is moved to T's basis.
    split = Split(d("2026-05-01"), Decimal(1), Decimal(4))
    stock = apple(["26"])
    found = reaction(APPLE_EVENT, stock, spy(["500"]), ny("2026-05-11T20:00:00"), CALENDAR, [split])
    assert found.base_close == Decimal(25) and found.windows[0].stock_return == Decimal("4.00")


def test_the_report_is_the_next_10q_or_10k_for_a_recent_period() -> None:
    def report(accession: str, form: str, filed: str, end: str) -> Report:
        return Report(accession, form, ny(filed), d(end), f"https://www.sec.gov/{accession}")

    reports = [
        report("prior-10q", "10-Q", "2026-01-30T18:00:00", "2025-12-27"),
        report("this-10q", "10-Q", "2026-05-01T06:01:00", "2026-03-28"),
        report("next-10q", "10-Q", "2026-07-31T06:00:00", "2026-06-27"),
        report("an-8k", "8-K", "2026-04-30T16:30:41", "2026-04-30"),
    ]
    assert match_report(APPLE_EVENT, reports) == reports[1]
    assert match_report(ny("2027-01-01T08:00:00"), reports) is None  # nothing recent enough


@dataclass(frozen=True)
class F:
    metric_id: str
    value: Decimal
    period_start: date | None
    period_end: date
    reported_at: datetime


def ytd(metric: str, year: int, values: tuple[int, ...], fiscal_year: bool = True) -> list[F]:
    ends = ("03-31", "06-30", "09-30", "12-31")
    total, out = 0, []
    for i, value in enumerate(values):
        total += value
        end = d(f"{year}-{ends[i]}")
        out.append(
            F(
                metric,
                Decimal(total),
                d(f"{year}-01-01"),
                end,
                datetime.combine(end, datetime.min.time(), UTC) + timedelta(days=30),
            )
        )
    return out


def three_months(metric: str, year: int, values: tuple[str, ...]) -> list[F]:
    starts, ends = ("01-01", "04-01", "07-01", "10-01"), ("03-31", "06-30", "09-30", "12-31")
    return [
        F(
            metric,
            Decimal(v),
            d(f"{year}-{starts[i]}"),
            d(f"{year}-{ends[i]}"),
            datetime.combine(d(f"{year}-{ends[i]}"), datetime.min.time(), UTC) + timedelta(days=30),
        )
        for i, v in enumerate(values)
    ]


def company() -> list[F]:
    facts: list[F] = []
    for metric, by_year in {
        "revenue": {2025: (100, 110, 120, 130), 2026: (120, 132)},
        "gross_profit": {2025: (40, 44, 48, 52), 2026: (54, 60)},
        "net_income": {2025: (10, 11, 12, 13), 2026: (15, 16)},
        "operating_cash_flow": {2025: (20, 20, 20, 20), 2026: (25, 30)},
        "capex": {2025: (5, 5, 5, 5), 2026: (5, 6)},
    }.items():
        for year, values in by_year.items():
            facts += ytd(metric, year, values)
    # EPS as filings tag it: three months, year to date and the year; never a fourth quarter.
    facts += three_months("eps_diluted", 2025, ("1.00", "1.10", "1.20"))
    facts += three_months("eps_diluted", 2026, ("1.50", "1.60"))
    facts += [f for f in ytd("eps_diluted", 2025, (1, 1, 1, 1)) if f.period_end.month in (6, 9, 12)]
    facts += [f for f in ytd("eps_diluted", 2026, (1, 2)) if f.period_end.month == 6]
    return facts


def by_metric(found: list[Actual[F]]) -> dict[str, Actual[F]]:
    return {a.metric: a for a in found}


def test_the_quarter_against_the_quarter_before_and_a_year_earlier() -> None:
    found = by_metric(actuals(company(), d("2026-06-30"), datetime(2026, 9, 1, tzinfo=UTC), []))
    revenue = found["revenue"]
    assert (revenue.current.value, revenue.prior_quarter.value, revenue.year_ago.value) == (
        Decimal(132),
        Decimal(120),
        Decimal(110),
    )
    assert (revenue.change_qoq, revenue.change_yoy) == (Decimal("10.00"), Decimal("20.00"))
    margin = found["gross_margin"]
    assert (margin.current.value, margin.year_ago.value, margin.change_yoy, margin.change_unit) == (
        Decimal("45.45"),  # 60 / 132
        Decimal("40.00"),  # 44 / 110
        Decimal("5.45"),
        "percentage points",
    )
    fcf = found["free_cash_flow"]
    assert (fcf.current.value, fcf.change_yoy) == (Decimal(24), Decimal("60.00"))  # 30-6 vs 20-5
    eps = found["eps_diluted"]
    assert (eps.current.value, eps.change_yoy) == (Decimal("1.60"), Decimal("45.45"))


def test_a_fourth_quarter_eps_is_never_derived() -> None:
    found = by_metric(actuals(company(), d("2025-12-31"), datetime(2026, 3, 1, tzinfo=UTC), []))
    assert found["revenue"].current.value == Decimal(130)  # year - 9 months
    eps = found["eps_diluted"]
    assert (eps.current.value, eps.current.detail) == (
        None,
        "a fourth-quarter EPS is never derived (ADR-013)",
    )
    assert found["revenue"].current.inputs[0].note == "year minus 9 months"
