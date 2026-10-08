"""Fair value models (M1.3a, ADR-023)."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from autotrading.domain.fair_value import (
    DEFAULT_ASSUMPTIONS,
    Assumptions,
    RiskFree,
    dcf,
    fair_value,
    growth_path,
    known_at,
    month_ends,
    multiple_history,
    owner_fcf,
    relative,
    reverse_growth,
    snapshots,
)
from autotrading.domain.provenance import end_of_day
from autotrading.domain.valuation import NEW_YORK, Close, Input


@dataclass(frozen=True)
class F:
    metric_id: str
    value: Decimal
    period_start: date | None
    period_end: date
    reported_at: datetime


def year(metric: str, value: int) -> F:
    return F(
        metric,
        Decimal(value),
        date(2025, 1, 1),
        date(2025, 12, 31),
        datetime(2026, 2, 1, tzinfo=UTC),
    )


def quarters(metric: str, q: int) -> list[F]:
    """A full year plus the year-to-date values of the next half year: TTM = 4 x q."""
    reported = datetime(2026, 8, 1, tzinfo=UTC)
    return [
        F(metric, Decimal(4 * q), date(2025, 1, 1), date(2025, 12, 31), reported),
        F(metric, Decimal(q), date(2025, 1, 1), date(2025, 3, 31), reported),
        F(metric, Decimal(2 * q), date(2025, 1, 1), date(2025, 6, 30), reported),
        F(metric, Decimal(3 * q), date(2025, 1, 1), date(2025, 9, 30), reported),
        F(metric, Decimal(q), date(2026, 1, 1), date(2026, 3, 31), reported),
        F(metric, Decimal(2 * q), date(2026, 1, 1), date(2026, 6, 30), reported),
    ]


def test_growth_fades_linearly_to_the_terminal_rate() -> None:
    path = growth_path(Decimal("0.05"), Decimal("0.025"))
    assert path[:5] == [Decimal("0.05")] * 5
    assert path[5:] == [Decimal(x) for x in ("0.045", "0.04", "0.035", "0.03", "0.025")]


def test_dcf_matches_a_perpetuity_by_hand() -> None:
    # No growth at 10%: the value of 100 a year forever is 100 / 0.10 = 1,000.
    value = dcf(Decimal(100), Decimal(0), Decimal(0), Decimal("0.1"), Decimal(0), Decimal(1))
    assert value.enterprise_value.quantize(Decimal("0.000001")) == Decimal(1000)
    assert value.explicit_value.quantize(Decimal("0.0001")) == Decimal("614.4567")
    # Net debt is taken off the enterprise value before dividing by shares.
    per_share = dcf(Decimal(100), Decimal(0), Decimal(0), Decimal("0.1"), Decimal(200), Decimal(4))
    assert per_share.per_share.quantize(Decimal("0.000001")) == Decimal(200)


def test_reverse_dcf_finds_the_growth_the_price_implies() -> None:
    args = (Decimal(100), Decimal("0.025"), Decimal("0.09"), Decimal(50), Decimal(10))
    price = dcf(args[0], Decimal("0.07"), *args[1:]).per_share
    found = reverse_growth(price, *args)
    assert found == Decimal("0.0700")
    assert reverse_growth(Decimal(10**9), *args) is None  # beyond +100% a year


def test_assumptions_are_validated() -> None:
    with pytest.raises(ValidationError, match="bear <= base <= bull"):
        Assumptions(**{**DEFAULT_ASSUMPTIONS.model_dump(), "growth_bear": Decimal(12)})
    with pytest.raises(ValidationError):
        Assumptions(**{**DEFAULT_ASSUMPTIONS.model_dump(), "equity_risk_premium": Decimal(15)})
    with pytest.raises(ValidationError):
        Assumptions(**{**DEFAULT_ASSUMPTIONS.model_dump(), "extra": 1})
    with pytest.raises(ValidationError):  # percent to two decimals
        Assumptions(**{**DEFAULT_ASSUMPTIONS.model_dump(), "growth_base": Decimal("5.125")})
    # JSON numbers keep their decimal value (stored parameters read back exactly).
    parsed = Assumptions.model_validate_json(
        '{"equity_risk_premium": 5.1, "terminal_growth": "2.5", "growth_bear": 0,'
        ' "growth_base": 5, "growth_bull": 10.25, "subtract_sbc": false}'
    )
    assert (parsed.equity_risk_premium, parsed.growth_bull) == (Decimal("5.1"), Decimal("10.25"))
    assert Assumptions.model_validate(parsed.model_dump(mode="json")) == parsed


def company(sbc: int = 5) -> list[F]:
    return [
        *quarters("operating_cash_flow", 30),
        *quarters("capex", 5),
        *quarters("stock_based_compensation", sbc),
    ]


def test_owner_fcf_subtracts_sbc_unless_told_not_to() -> None:
    with_sbc = owner_fcf(company(), subtract_sbc=True)
    without = owner_fcf(company(), subtract_sbc=False)
    assert isinstance(with_sbc, Input) and with_sbc.value == Decimal(80)  # 120 - 20 - 20
    assert isinstance(without, Input) and without.value == Decimal(100)
    assert with_sbc.note and "SBC" in with_sbc.note
    # ExxonMobil reports no separate SBC line: say so, and that a version can leave it out.
    no_sbc = [f for f in company() if f.metric_id != "stock_based_compensation"]
    assert owner_fcf(no_sbc, subtract_sbc=True) == (
        "not reported for the last four quarters: stock-based compensation"
        " (an assumption set can leave SBC out)"
    )
    assert isinstance(owner_fcf(no_sbc, subtract_sbc=False), Input)


RISK_FREE = RiskFree(Decimal("4.0"), date(2026, 8, 13), datetime(2026, 8, 14, tzinfo=UTC))


def inputs(net_debt: int = 100, shares: int = 10) -> tuple[Input[F], Input[F]]:
    end = date(2026, 6, 30)
    return (
        Input("net_debt", Decimal(net_debt), None, end),
        Input("shares_outstanding_cover", Decimal(shares), None, end),
    )


def test_scenarios_price_comparison_and_reverse_dcf() -> None:
    debt, shares = inputs()
    result = fair_value(company(), DEFAULT_ASSUMPTIONS, RISK_FREE, debt, shares, Decimal(100))
    assert result.status == "ok" and result.discount_rate == Decimal("9.0")
    bear, base, bull = (result.scenarios[s].per_share for s in ("bear", "base", "bull"))
    assert bear < base < bull
    assert result.implied_upside == ((base / 100 - 1) * 100).quantize(Decimal("0.01"))
    assert result.margin_of_safety == ((base - 100) / base * 100).quantize(Decimal("0.01"))
    assert result.reverse_growth is not None
    # The implied growth, put back in, gives the price.
    again = dcf(
        Decimal(80),
        result.reverse_growth / 100,
        Decimal("0.025"),
        Decimal("0.09"),
        Decimal(100),
        Decimal(10),
    )
    assert abs(again.per_share - 100) < Decimal("0.05")


def test_same_inputs_same_output() -> None:
    debt, shares = inputs()
    first = fair_value(company(), DEFAULT_ASSUMPTIONS, RISK_FREE, debt, shares, Decimal(100))
    second = fair_value(company(), DEFAULT_ASSUMPTIONS, RISK_FREE, debt, shares, Decimal(100))
    assert first == second


def test_not_meaningful_unavailable_and_no_price() -> None:
    debt, shares = inputs()
    burning = [
        *quarters("operating_cash_flow", 5),
        *quarters("capex", 10),
        *quarters("stock_based_compensation", 1),
    ]
    assert (
        fair_value(burning, DEFAULT_ASSUMPTIONS, RISK_FREE, debt, shares, None).status
        == "not_meaningful"
    )
    missing = fair_value(company(), DEFAULT_ASSUMPTIONS, None, debt, shares, None)
    assert missing.status == "unavailable" and "Treasury" in (missing.detail or "")
    no_price = fair_value(company(), DEFAULT_ASSUMPTIONS, RISK_FREE, debt, shares, None)
    assert no_price.status == "ok" and no_price.scenarios
    assert (no_price.implied_upside, no_price.margin_of_safety, no_price.reverse_growth) == (
        None,
        None,
        None,
    )
    tight = Assumptions(**{**DEFAULT_ASSUMPTIONS.model_dump(), "terminal_growth": Decimal(5)})
    low_rate = RiskFree(
        Decimal("0.5"), RISK_FREE.observation_date, RISK_FREE.published_at
    )  # r = 5.5%
    assert "terminal growth" in (
        fair_value(company(), tight, low_rate, debt, shares, None).detail or ""
    )


def test_relative_valuation_percentile_and_median() -> None:
    history = [
        (date(2020, m, 28), Decimal(v)) for m, v in zip(range(1, 11), range(10, 20), strict=True)
    ]
    result = relative("pe_ratio_ttm", Decimal("15"), history)
    assert (result.median, result.percentile, result.observations) == (
        Decimal("14.50"),
        Decimal(60),
        10,
    )
    assert relative("pe_ratio_ttm", None, []).percentile is None


@dataclass(frozen=True)
class Row:
    key: str
    value: int
    published: datetime
    recorded: datetime


def test_in_memory_as_of_takes_the_latest_version_published_by_then() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [
        Row("a", 1, t0, t0),
        Row("a", 2, t0 + timedelta(days=10), t0 + timedelta(days=10)),
        Row("b", 3, t0 + timedelta(days=20), t0 + timedelta(days=20)),
    ]

    def pick(at: datetime) -> dict[str, int]:
        return {
            r.key: r.value
            for r in known_at(
                rows, at, lambda r: (r.key,), lambda r: r.published, lambda r: r.recorded
            )
        }

    assert pick(t0 + timedelta(days=5)) == {"a": 1}
    assert pick(t0 + timedelta(days=30)) == {"a": 2, "b": 3}


def test_snapshots_match_as_of_at_every_time() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [
        Row("a", 1, t0, t0),
        Row("b", 3, t0 + timedelta(days=20), t0 + timedelta(days=20)),
        Row("a", 2, t0 + timedelta(days=10), t0 + timedelta(days=10)),
        Row("a", 9, t0 + timedelta(days=10), t0 + timedelta(days=11)),  # recorded later
    ]
    times = [t0 + timedelta(days=n) for n in (-1, 5, 10, 30)]
    seen = [
        {r.key: r.value for r in rows_then}
        for _, rows_then in snapshots(
            rows, times, lambda r: (r.key,), lambda r: r.published, lambda r: r.recorded
        )
    ]
    assert seen == [{}, {"a": 1}, {"a": 9}, {"a": 9, "b": 3}]


def test_month_ends_are_the_last_calendar_day_in_new_york() -> None:
    # 2024-03-31 ends at 03:59:59 UTC on April 1: not over yet at 23:00 UTC on March 31.
    points = month_ends(date(2024, 1, 1), datetime(2024, 3, 31, 23, tzinfo=UTC))
    assert [p.astimezone(NEW_YORK).date() for p in points] == [date(2024, 1, 31), date(2024, 2, 29)]
    assert month_ends(date(2024, 1, 1), datetime(2024, 1, 30, tzinfo=UTC)) == []


def eps_year(value: str, reported: datetime) -> F:
    return F("eps_diluted", Decimal(value), date(2025, 1, 1), date(2025, 12, 31), reported)


def close_on(day: date, value: str = "220") -> Close:
    return Close(day, Decimal(value), "end_of_day", end_of_day(day))


def test_history_uses_what_was_known_at_each_month_end() -> None:
    original = eps_year("10", datetime(2026, 2, 1, tzinfo=UTC))
    restated = eps_year("11", datetime(2026, 4, 10, tzinfo=UTC))
    march, april, may = (
        end_of_day(date(2026, 3, 31)),
        end_of_day(date(2026, 4, 30)),
        end_of_day(date(2026, 5, 29)),
    )
    history = multiple_history(
        [(march, [original]), (april, [restated]), (may, [restated])],
        [close_on(date(2026, 3, 31)), close_on(date(2026, 4, 30)), close_on(date(2026, 5, 15))],
        [],
    )
    # May's last close is two weeks old: no valuation price, so no point.
    assert history["pe_ratio_ttm"] == [
        (date(2026, 3, 31), Decimal("22.00")),
        (date(2026, 4, 30), Decimal("20.00")),
    ]
    assert history["ev_to_sales"] == []  # never reported
