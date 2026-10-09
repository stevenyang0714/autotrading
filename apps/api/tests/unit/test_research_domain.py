"""Research Record (M1.3b, ADR-024): economics, quality and capital allocation per period."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from autotrading.domain.research import Window, research_record
from autotrading.domain.splits import Split
from autotrading.domain.valuation import Valued


@dataclass(frozen=True)
class F:
    metric_id: str
    value: Decimal
    period_start: date | None
    period_end: date
    reported_at: datetime


AT = datetime(2026, 8, 15, tzinfo=UTC)


def d(text: str) -> date:
    return date.fromisoformat(text)


def reported(year: int, month: int) -> datetime:
    return datetime(year, month, 1, tzinfo=UTC)


def year_flows(metric: str, year: int, q: tuple[int, int, int, int]) -> list[F]:
    """A calendar fiscal year: the year and its year-to-date values, as 10-K and 10-Qs."""
    start = date(year, 1, 1)
    at = reported(year + 1, 2)
    return [
        F(metric, Decimal(sum(q)), start, date(year, 12, 31), at),
        F(metric, Decimal(q[0]), start, date(year, 3, 31), at),
        F(metric, Decimal(q[0] + q[1]), start, date(year, 6, 30), at),
        F(metric, Decimal(q[0] + q[1] + q[2]), start, date(year, 9, 30), at),
    ]


def half_flows(metric: str, year: int, q1: int, q2: int) -> list[F]:
    """The first half of a year in progress (Q1 and six months to date)."""
    start = date(year, 1, 1)
    return [
        F(metric, Decimal(q1), start, date(year, 3, 31), reported(year, 5)),
        F(metric, Decimal(q1 + q2), start, date(year, 6, 30), reported(year, 8)),
    ]


def split_year(total: int) -> tuple[int, int, int, int]:
    """Four quarters adding up to `total` exactly (the first takes the remainder)."""
    base = total // 4
    return (total - 3 * base, base, base, base)


def flows(metric: str, by_year: dict[int, int], half: tuple[int, int] | None = None) -> list[F]:
    """Quarters per year adding up to the year, plus the first half of 2026."""
    out = [f for y, total in by_year.items() for f in year_flows(metric, y, split_year(total))]
    return out + (half_flows(metric, 2026, *half) if half else [])


def instant(metric: str, day: str, value: int) -> F:
    return F(metric, Decimal(value), None, d(day), reported(int(day[:4]) + 1, 2))


def company(
    equity: tuple[int, int, int] = (300, 340, 360),
    tax_2025: int = 22,
    pretax_2025: int = 110,
    dividends: bool = True,
    with_dna: bool = True,
) -> list[F]:
    """FY2024 and FY2025 (Jan-Dec) plus the first half of 2026."""
    facts = [
        *flows("revenue", {2024: 320, 2025: 400}, (110, 110)),
        *flows("gross_profit", {2024: 160, 2025: 200}, (55, 55)),
        *flows("operating_income", {2024: 96, 2025: 120}, (32, 32)),
        *flows("pretax_income", {2024: 88, 2025: pretax_2025}, (30, 30)),
        *flows("income_tax_expense", {2024: 16, 2025: tax_2025}, (6, 6)),
        *flows("net_income", {2024: 72, 2025: 88}, (24, 24)),
        *flows("operating_cash_flow", {2024: 120, 2025: 132}, (35, 35)),
        *flows("capex", {2024: 24, 2025: 32}, (8, 8)),
        *flows("share_repurchases", {2024: 40, 2025: 48}, (12, 12)),
        *flows("stock_based_compensation", {2024: 12, 2025: 16}, (4, 4)),
        # Balance sheets: opening of FY2025 (2024-12-31), its end, the TTM ends.
        instant("stockholders_equity", "2024-12-31", equity[0]),
        instant("stockholders_equity", "2025-12-31", equity[1]),
        instant("stockholders_equity", "2025-06-30", equity[1]),
        instant("stockholders_equity", "2026-06-30", equity[2]),
        instant("long_term_debt_noncurrent", "2024-12-31", 200),
        instant("long_term_debt_noncurrent", "2025-12-31", 200),
        instant("long_term_debt_current", "2025-12-31", 20),
        instant("long_term_debt_noncurrent", "2025-06-30", 200),
        instant("long_term_debt_noncurrent", "2026-06-30", 180),
        instant("cash", "2024-12-31", 100),
        instant("cash", "2025-12-31", 120),
        instant("cash", "2025-06-30", 110),
        instant("cash", "2026-06-30", 90),
    ]
    if with_dna:
        facts += flows("depreciation_amortization", {2024: 16, 2025: 20}, (6, 6))
    if dividends:
        facts += flows("dividends_paid", {2024: 8, 2025: 12}, (3, 3))
    return facts


def column(facts: list[F], end: str, splits: list[Split] | None = None) -> dict[str, Valued[F]]:
    record = research_record(facts, AT, splits or [])
    index = next(i for i, p in enumerate(record.periods) if p.end == d(end))
    return {metric: values[index] for _, metric, _, values in record.rows}


def value(result: Valued[F]) -> Decimal | None:
    return result.value


def test_periods_are_ttm_then_five_fiscal_years_newest_first() -> None:
    record = research_record(company(), AT, [])
    assert record.periods == [
        Window("ttm", d("2025-07-01"), d("2026-06-30")),
        Window("fiscal_year", d("2025-01-01"), d("2025-12-31")),
        Window("fiscal_year", d("2024-01-01"), d("2024-12-31")),
    ]
    assert [metric for _, metric, _, _ in record.rows][:4] == [
        "revenue_growth",
        "gross_margin",
        "operating_margin",
        "net_margin",
    ]


def test_fiscal_year_values_by_hand() -> None:
    fy = column(company(), "2025-12-31")
    expected = {
        "revenue_growth": "25.00",  # 400 / 320 - 1
        "gross_margin": "50.00",
        "operating_margin": "30.00",
        "net_margin": "22.00",
        "effective_tax_rate": "20.00",  # 22 / 110
        "roic": "22.86",  # 120 x 0.8 / avg(300+200-100, 340+220-120)
        "roe": "27.50",  # 88 / avg(300, 340)
        "fcf_conversion": "113.64",  # (132 - 32) / 88
        "net_debt_to_ebitda": "0.71",  # (220 - 120) / (120 + 20)
        "free_cash_flow": "100",
        "share_repurchases": "48",
        "dividends_paid": "12",
        "stock_based_compensation": "16",
        "cash_returned": "60",
        "cash_returned_to_fcf": "60.00",
    }
    assert {m: str(fy[m].value) for m in expected} == expected
    roic = fy["roic"]
    assert [i.name for i in roic.inputs] == ["nopat", "invested_capital", "invested_capital"]
    assert roic.inputs[0].value == Decimal(96)
    # Unreported short-term debt is counted as 0 and named (D4).
    opening = roic.inputs[1]
    assert opening.value == Decimal(400) and opening.note is not None
    assert "long_term_debt_current" in opening.note and "commercial_paper" in opening.note


def test_ttm_uses_the_last_four_quarters_and_the_four_before() -> None:
    ttm = column(company(), "2026-06-30")
    # Revenue: 2025 H2 (200) + 2026 H1 (220) against 2024 H2 (160) + 2025 H1 (200).
    assert ttm["revenue_growth"].value == Decimal("16.67")
    assert ttm["gross_margin"].value == Decimal("50.00")
    revenue = ttm["gross_margin"].inputs[1]
    assert (revenue.name, revenue.value, revenue.note) == (
        "revenue_ttm",
        Decimal(420),
        "sum of the last four quarters",
    )
    # Equity on 2025-06-30 and 2026-06-30: the quarter end a year earlier opens the period.
    roe = ttm["roe"]
    assert [i.period_end for i in roe.inputs[1:]] == [d("2025-06-30"), d("2026-06-30")]


def test_without_the_year_before_growth_is_unavailable_and_named() -> None:
    later = [f for f in company() if f.period_end.year >= 2025 or f.period_start is None]
    fy = column(later, "2025-12-31")
    assert (fy["revenue_growth"].reason, fy["revenue_growth"].detail) == (
        "unavailable",
        "not reported: revenue a year earlier",
    )


def test_negative_equity_makes_roe_nm_but_roic_still_counts() -> None:
    fy = column(company(equity=(-50, -30, -20)), "2025-12-31")  # AutoZone, O'Reilly, Lowe's
    assert (fy["roe"].reason, fy["roe"].detail) == (
        "not_meaningful",
        "stockholders' equity on 2024-12-31 is not positive",
    )
    # Invested capital = -50 + 200 - 100 = 50 and -30 + 220 - 120 = 70: positive.
    assert fy["roic"].value == Decimal("160.00")  # 96 / 60


def test_tax_edge_cases() -> None:
    loss = column(company(pretax_2025=-10, tax_2025=2), "2025-12-31")
    assert loss["effective_tax_rate"].reason == "not_meaningful"
    assert (loss["roic"].reason, loss["roic"].detail) == (
        "not_meaningful",
        "pretax income is not positive",
    )
    benefit = column(company(tax_2025=-5), "2025-12-31")  # NVDA FY2023 style
    rate = benefit["effective_tax_rate"]
    assert rate.value == Decimal("-4.55") and rate.detail == "a tax benefit: the rate is negative"
    assert benefit["roic"].value is not None and benefit["roic"].detail is not None


def test_missing_inputs_are_named_never_estimated() -> None:
    no_gross = [f for f in company(with_dna=False) if f.metric_id != "gross_profit"]
    fy = column(no_gross, "2025-12-31")
    assert fy["gross_margin"].detail == "not reported: gross profit"  # Alphabet, Meta
    assert fy["net_debt_to_ebitda"].detail == "not reported: depreciation and amortization"
    assert fy["operating_margin"].value == Decimal("30.00")  # the rest still stands


def test_dividends_count_as_zero_only_when_none_are_reported() -> None:
    none = column(company(dividends=False), "2025-12-31")  # AutoZone, O'Reilly
    assert none["dividends_paid"].value == Decimal(0)
    assert none["dividends_paid"].detail == "not reported for this period, counted as 0"
    assert none["cash_returned"].value == Decimal(48)
    assert none["cash_returned_to_fcf"].value == Decimal("48.00")
    # Paid in other periods but not reported for this one: unavailable, not 0.
    gap = [
        f
        for f in company()
        if not (f.metric_id == "dividends_paid" and f.period_end == d("2025-12-31"))
    ]
    fy = column(gap, "2025-12-31")
    assert (fy["dividends_paid"].reason, fy["cash_returned"].reason) == (
        "unavailable",
        "unavailable",
    )


def test_diluted_share_change_on_one_split_basis() -> None:
    split = Split(d("2025-06-02"), Decimal(1), Decimal(4))  # 4-for-1, effective mid-2025
    facts = [
        *company(),
        F("diluted_shares", Decimal(26), d("2024-01-01"), d("2024-12-31"), reported(2025, 2)),
        F("diluted_shares", Decimal(100), d("2025-01-01"), d("2025-12-31"), reported(2026, 2)),
    ]
    fy = column(facts, "2025-12-31", [split])
    change = fy["diluted_shares_change"]
    assert change.value == Decimal("-3.85")  # 100 / (26 x 4) - 1
    before = change.inputs[1]
    assert before.value == Decimal(104) and before.note is not None and "factor 4" in before.note


def test_ttm_diluted_change_is_the_latest_quarter_against_a_year_earlier() -> None:
    def shares(value: str, start: str, end: str, at: datetime) -> F:
        return F("diluted_shares", Decimal(value), d(start), d(end), at)

    # 10-Qs report weighted shares for the quarter and the year to date; 10-Ks for the year.
    facts = [
        *company(),
        shares("103", "2025-01-01", "2025-03-31", reported(2025, 5)),
        shares("102", "2025-04-01", "2025-06-30", reported(2025, 8)),
        shares("102.5", "2025-01-01", "2025-06-30", reported(2025, 8)),
        shares("101", "2025-01-01", "2025-12-31", reported(2026, 2)),
        shares("100", "2026-01-01", "2026-03-31", reported(2026, 5)),
        shares("99", "2026-04-01", "2026-06-30", reported(2026, 8)),
        shares("99.5", "2026-01-01", "2026-06-30", reported(2026, 8)),
    ]
    ttm = column(facts, "2026-06-30")
    assert ttm["diluted_shares_change"].value == Decimal("-2.94")  # 99 / 102 - 1
    assert column(company(), "2026-06-30")["diluted_shares_change"].detail == (
        "not reported: diluted shares, diluted shares a year earlier"
    )


def test_a_missing_derived_input_is_explained_by_its_missing_part() -> None:
    bank = [f for f in company() if f.metric_id != "capex"]  # JPMorgan reports no capex
    fy = column(bank, "2025-12-31")
    assert fy["free_cash_flow"].detail == "not reported: capex"
    assert fy["fcf_conversion"].detail == "not reported: capex"
    assert fy["cash_returned_to_fcf"].detail == "not reported: capex"
    gap = [
        f
        for f in company()
        if not (f.metric_id == "dividends_paid" and f.period_end == d("2025-12-31"))
    ]
    assert column(gap, "2025-12-31")["cash_returned_to_fcf"].detail == (
        "not reported: dividends paid"
    )
