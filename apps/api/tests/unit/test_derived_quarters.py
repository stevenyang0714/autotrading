"""Derived metrics, quarters from year-to-date values, trailing twelve months (ADR-021)."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from autotrading.domain.derived import derive_all, free_cash_flow, net_debt, total_debt
from autotrading.domain.quarters import quarters, trailing_twelve_months


@dataclass(frozen=True)
class F:
    metric_id: str
    value: Decimal
    period_start: date | None
    period_end: date


def d(text: str) -> date:
    return date.fromisoformat(text)


def index(*facts: F) -> dict[tuple[str, date | None, date], F]:
    return {(f.metric_id, f.period_start, f.period_end): f for f in facts}


FY_START, FY_END = d("2024-09-29"), d("2025-09-27")  # Apple FY2025, 52 weeks


def test_free_cash_flow_needs_both_inputs() -> None:
    ocf = F("operating_cash_flow", Decimal(111482), FY_START, FY_END)
    capex = F("capex", Decimal(12715), FY_START, FY_END)
    fcf = free_cash_flow(index(ocf, capex), FY_START, FY_END)
    assert fcf is not None and fcf.value == Decimal(98767)
    assert [m for m, _ in fcf.inputs] == ["operating_cash_flow", "capex"]
    assert free_cash_flow(index(ocf), FY_START, FY_END) is None  # e.g. JPMorgan: no capex


def test_total_debt_counts_unreported_short_items_as_zero_and_says_so() -> None:
    end = d("2025-12-31")
    noncurrent = F("long_term_debt_noncurrent", Decimal(28800), None, end)
    debt = total_debt(index(noncurrent), end)
    assert debt is not None
    assert (debt.value, debt.assumed_zero) == (
        Decimal(28800),
        ("long_term_debt_current", "commercial_paper"),
    )
    full = index(
        F("long_term_debt_noncurrent", Decimal(78328), None, FY_END),
        F("long_term_debt_current", Decimal(12350), None, FY_END),
        F("commercial_paper", Decimal(7979), None, FY_END),
        F("cash", Decimal(35934), None, FY_END),
    )
    total = total_debt(full, FY_END)
    assert total is not None and (total.value, total.assumed_zero) == (Decimal(98657), ())
    net = net_debt(full, FY_END)
    assert net is not None and net.value == Decimal(62723)


def test_no_total_debt_without_non_current_debt() -> None:
    end = d("2025-12-31")
    bank = index(F("commercial_paper", Decimal(1), None, end), F("cash", Decimal(5), None, end))
    assert total_debt(bank, end) is None
    assert net_debt(bank, end) is None
    assert derive_all(bank.values()) == []


def ytd(metric: str, value: int, end: str, start: date = FY_START) -> F:
    return F(metric, Decimal(value), start, d(end))


APPLE_FY2025_REVENUE = [
    ytd("revenue", 124300, "2024-12-28"),  # Q1, 90 days
    ytd("revenue", 219659, "2025-03-29"),  # 6 months
    ytd("revenue", 313695, "2025-06-28"),  # 9 months
    ytd("revenue", 416161, "2025-09-27"),  # year
]


def test_quarters_are_differenced_from_year_to_date_values_and_add_up() -> None:
    series = quarters(APPLE_FY2025_REVENUE, "revenue")
    assert [(q.number, q.value, q.method) for q in series] == [
        (1, Decimal(124300), "reported"),
        (2, Decimal(95359), "ytd_difference"),
        (3, Decimal(94036), "ytd_difference"),
        (4, Decimal(102466), "year_minus_9_months"),
    ]
    assert sum(q.value for q in series) == Decimal(416161)
    assert series[1].period_start == d("2024-12-29") and series[1].period_end == d("2025-03-29")
    assert all(q.fiscal_year_end == FY_END for q in series)


def test_a_missing_year_to_date_value_leaves_its_quarters_unavailable() -> None:
    without_six_months = [f for f in APPLE_FY2025_REVENUE if f.period_end != d("2025-03-29")]
    assert [q.number for q in quarters(without_six_months, "revenue")] == [1, 4]


def test_the_year_in_progress_starts_the_day_after_the_last_year() -> None:
    next_q1 = ytd("revenue", 143756, "2025-12-27", start=d("2025-09-28"))
    series = quarters([*APPLE_FY2025_REVENUE, next_q1], "revenue")
    assert (series[-1].number, series[-1].fiscal_year_end, series[-1].value) == (
        1,
        None,
        Decimal(143756),
    )
    ttm = trailing_twelve_months(series)
    assert ttm is not None and ttm[0] == Decimal(95359 + 94036 + 102466 + 143756)


def test_a_53_week_year_has_a_14_week_quarter() -> None:
    start = d("2022-09-25")  # Apple FY2023 has 53 weeks: Q1 is 14 weeks
    facts = [
        ytd("revenue", 117154, "2022-12-31", start),  # 97 days
        ytd("revenue", 211990, "2023-04-01", start),
        ytd("revenue", 293787, "2023-07-01", start),
        ytd("revenue", 383285, "2023-09-30", start),  # 370 days
    ]
    assert [q.number for q in quarters(facts, "revenue")] == [1, 2, 3, 4]


def test_eps_quarters_are_only_the_reported_three_months_and_no_fourth() -> None:
    facts = [
        ytd("eps_diluted", 243, "2024-12-28"),
        ytd("eps_diluted", 408, "2025-03-29"),
        F("eps_diluted", Decimal("1.65"), d("2024-12-29"), d("2025-03-29")),
        ytd("eps_diluted", 742, "2025-09-27"),
    ]
    series = quarters(facts, "eps_diluted")
    assert [(q.number, q.value) for q in series] == [(1, Decimal(243)), (2, Decimal("1.65"))]
    assert trailing_twelve_months(series) is None


def test_ttm_needs_four_consecutive_quarters() -> None:
    gap = [f for f in APPLE_FY2025_REVENUE if f.period_end != d("2025-03-29")]
    assert trailing_twelve_months(quarters(gap, "revenue")) is None
