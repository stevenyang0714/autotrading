"""Valuation inputs and multiples (M1.2, ADR-022)."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from autotrading.domain.splits import Split
from autotrading.domain.valuation import (
    Close,
    close_basis,
    select_price,
    share_count,
    ttm_eps,
    valuation,
)


@dataclass(frozen=True)
class F:
    metric_id: str
    value: Decimal
    period_start: date | None
    period_end: date
    reported_at: datetime


def d(text: str) -> date:
    return date.fromisoformat(text)


def t(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


AT = t("2026-08-15T00:00:00")


def close(day: str, value: str = "200", status: str = "end_of_day") -> Close:
    """A raw daily close, public at the end of its New York day."""
    end_of_day = datetime.combine(d(day), time(23, 59, 59), tzinfo=ZoneInfo("America/New_York"))
    return Close(d(day), Decimal(value), status, end_of_day)


def test_only_an_end_of_day_close_public_by_then_and_recent_is_used() -> None:
    assert select_price([close("2026-08-13")], AT).status == "ok"
    assert select_price([close("2026-08-13", status="fixture")], AT).status == "fixture"
    stale = select_price([close("2026-08-07")], AT)
    assert stale.status == "stale" and "older than five days" in stale.detail
    assert select_price([close("2026-08-16")], AT).status == "none"  # not public yet
    assert select_price([], AT).status == "none"


def test_shares_are_the_latest_dated_count_on_the_close_basis() -> None:
    # NVDA: the May 2024 10-Q cover count, before the 10-for-1 split of 2024-06-10.
    cover = F(
        "shares_outstanding_cover",
        Decimal(2_464_000_000),
        None,
        d("2024-05-17"),
        t("2024-05-29T20:00:00"),
    )
    balance = F(
        "shares_outstanding",
        Decimal(2_462_000_000),
        None,
        d("2024-04-28"),
        t("2024-05-29T20:00:00"),
    )
    split = Split(d("2024-06-10"), Decimal(1), Decimal(10))
    after = share_count([cover, balance], close_basis(close("2024-06-12")), [split])
    assert after is not None and (after.name, after.value) == (
        "shares_outstanding_cover",
        Decimal(24_640_000_000),
    )
    before = share_count([cover, balance], close_basis(close("2024-06-07")), [split])
    assert before is not None and before.value == Decimal(2_464_000_000)


def eps(value: str, start: str, end: str, reported: str = "2026-01-01T00:00:00") -> F:
    return F("eps_diluted", Decimal(value), d(start), d(end), t(reported))


def test_ttm_eps_is_fiscal_year_plus_this_year_to_date_minus_last() -> None:
    facts = [
        eps("6.08", "2023-10-01", "2024-09-28"),  # FY2024
        eps("6.08", "2024-09-29", "2025-06-28"),  # FY2025 nine months
        eps("4.60", "2023-10-01", "2024-06-29"),  # FY2024 nine months
    ]
    value = ttm_eps(facts, AT, [])
    assert value is not None and value.value == Decimal("7.56")
    assert value.note == "fiscal year + 9 months this year - 9 months last year"
    only_year = ttm_eps(facts[:1], AT, [])
    assert only_year is not None and only_year.value == Decimal("6.08")
    assert ttm_eps(facts[:2], AT, []) is None  # last year's nine months missing


def fact(metric: str, value: int, start: str | None, end: str) -> F:
    return F(metric, Decimal(value), d(start) if start else None, d(end), t("2026-08-01T20:00:00"))


def quarterly(metric: str, values: tuple[int, int, int, int]) -> list[F]:
    """A fiscal year Jan-Dec 2025 and the first half of 2026, year-to-date like 10-Qs."""
    q1, q2, q3, q4 = values
    return [
        fact(metric, q1 + q2 + q3 + q4, "2025-01-01", "2025-12-31"),
        fact(metric, q1, "2025-01-01", "2025-03-31"),
        fact(metric, q1 + q2, "2025-01-01", "2025-06-30"),
        fact(metric, q1 + q2 + q3, "2025-01-01", "2025-09-30"),
        fact(metric, q1, "2026-01-01", "2026-03-31"),
        fact(metric, q1 + q2, "2026-01-01", "2026-06-30"),
    ]


def company(equity: int = 400, capex: tuple[int, int, int, int] = (5, 5, 5, 5)) -> list[F]:
    return [
        *quarterly("revenue", (100, 100, 100, 100)),
        *quarterly("operating_income", (30, 30, 30, 30)),
        *quarterly("depreciation_amortization", (5, 5, 5, 5)),
        *quarterly("operating_cash_flow", (25, 25, 25, 25)),
        *quarterly("capex", capex),
        fact("shares_outstanding_cover", 10, None, "2026-07-20"),
        fact("long_term_debt_noncurrent", 300, None, "2026-06-30"),
        fact("cash", 100, None, "2026-06-30"),
        fact("stockholders_equity", equity, None, "2026-06-30"),
        eps("10.00", "2025-01-01", "2025-12-31"),
        eps("5.00", "2026-01-01", "2026-06-30"),
        eps("4.00", "2025-01-01", "2025-06-30"),
    ]


def values(result: list[Any]) -> dict[str, tuple[Decimal | None, str | None]]:
    return {v.metric_id: (v.value, v.reason) for v in result}


def test_every_multiple_from_its_inputs() -> None:
    price = select_price([close("2026-08-13", "220")], AT)
    result = values(valuation(company(), price, []))
    assert result == {
        "market_cap": (Decimal(2200), None),  # 220 x 10
        "enterprise_value": (Decimal(2400), None),  # + 300 debt - 100 cash
        "pe_ratio_ttm": (Decimal("20.00"), None),  # 220 / (10 + 5 - 4)
        "ev_to_ebitda": (Decimal("17.14"), None),  # 2400 / (120 + 20)
        "ev_to_sales": (Decimal("6.00"), None),  # 2400 / 400
        "price_to_book": (Decimal("5.50"), None),  # 2200 / 400
        "fcf_yield": (Decimal("3.64"), None),  # (100 - 20) / 2200
        "earnings_yield": (Decimal("5.00"), None),  # 11 / 220
    }


def test_every_value_names_its_inputs() -> None:
    price = select_price([close("2026-08-13", "220")], AT)
    for value in valuation(company(), price, []):
        assert value.inputs, value.metric_id
        assert all(i.period_end is not None for i in value.inputs)


def test_negative_equity_and_missing_inputs() -> None:
    price = select_price([close("2026-08-13", "220")], AT)
    no_dna = [f for f in company(equity=-50) if f.metric_id != "depreciation_amortization"]
    result = values(valuation(no_dna, price, []))
    assert result["price_to_book"] == (None, "not_meaningful")  # AutoZone, O'Reilly
    assert result["ev_to_ebitda"] == (None, "unavailable")  # Microsoft, Alphabet
    assert result["ev_to_sales"][1] is None


def test_no_value_from_a_fixture_or_stale_close() -> None:
    for status, day in (("fixture", "2026-08-13"), ("end_of_day", "2026-08-01")):
        price = select_price([close(day, "220", status)], AT)
        result = valuation(company(), price, [])
        assert {v.value for v in result} == {None}
        assert {v.reason for v in result} == {"unavailable"}
        assert all("no valuation price" in (v.detail or "") for v in result)
