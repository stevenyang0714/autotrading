"""Price, trend and factor measures (M2.2, ADR-030)."""

import math
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from autotrading.domain.factors import (
    Dividend,
    FactorDefinitionsFile,
    Measure,
    Series,
    dividend_gaps,
    known_closes,
    known_dividends,
    price_measures,
    total_returns,
)
from autotrading.domain.provenance import end_of_day
from autotrading.domain.splits import Split
from autotrading.domain.valuation import Close
from autotrading.settings import get_settings

DEFINITIONS = FactorDefinitionsFile.model_validate(
    yaml.safe_load(
        Path(get_settings().resolved_config_dir() / "factor_definitions.yaml").read_text()
    )
).active()
# A released version never changes (ADR-030): a new definition_version is the only way to edit.
PINNED = {"0.1.0": "c6c48b837f99adfe052cc8dd85cc7a5db58aa58bfd6496d401525655e53b0605"}
LAST = date(2026, 10, 9)  # a Friday
T = end_of_day(LAST)


def sessions(count: int, last: date = LAST) -> list[date]:
    """`count` weekdays ending at `last`, oldest first."""
    days: list[date] = []
    day = last
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    return list(reversed(days))


def closes(values: list[float], last: date = LAST) -> list[Close]:
    return [
        Close(day, Decimal(str(v)), "end_of_day", end_of_day(day))
        for day, v in zip(sessions(len(values), last), values, strict=True)
    ]


def series(symbol: str, values: list[float], **kwargs: object) -> Series:
    return Series(
        symbol,
        closes(values),
        kwargs.get("splits", []),  # type: ignore[arg-type]
        kwargs.get("dividends", []),  # type: ignore[arg-type]
    )


def by_id(measures: list[Measure]) -> dict[str, Measure]:
    return {m.measure_id: m for m in measures}


def growing(count: int, daily: float, start: float = 100.0) -> list[float]:
    return [round(start * (1 + daily) ** i, 6) for i in range(count)]


def test_the_active_definition_set_is_pinned() -> None:
    assert DEFINITIONS.definition_version == "0.1.0"
    assert DEFINITIONS.content_sha256() == PINNED["0.1.0"]


def test_momentum_skips_the_last_month_and_reversal_is_the_last_month() -> None:
    values = [100.0] * 232 + [110.0] * 21  # flat for a year, then +10% in the last month
    found = by_id(price_measures(DEFINITIONS, T, series("AAPL", values), None)[0])
    assert found["momentum_12_1"].value == Decimal("0.00")
    assert found["momentum_6_1"].value == Decimal("0.00")
    assert found["reversal_1m"].value == Decimal("10.00")
    # 12-1: from the close 252 sessions back to the close 21 sessions back
    assert (found["momentum_12_1"].start, found["momentum_12_1"].end) == (
        sessions(253)[0],
        sessions(22)[0],
    )


def test_too_few_closes_are_unavailable_never_guessed() -> None:
    found = by_id(price_measures(DEFINITIONS, T, series("AAPL", [100.0] * 200), None)[0])
    assert found["momentum_12_1"].reason == "unavailable"
    assert found["momentum_12_1"].detail == "200 closes known; 253 needed"
    assert found["close_vs_sma_200"].value == Decimal("0.00")  # exactly enough
    assert found["momentum_6_1"].value == Decimal("0.00")


def test_a_stale_last_close_makes_every_price_measure_unavailable() -> None:
    later = T + timedelta(days=6)
    measures = price_measures(DEFINITIONS, later, series("AAPL", [100.0] * 300), None)[0]
    assert {m.reason for m in measures} == {"unavailable"}
    assert "older than 5 days" in measures[0].detail
    # the benchmark's own beta and relative measures stay not meaningful
    spy = by_id(price_measures(DEFINITIONS, later, series("SPY", [100.0] * 300), None)[0])
    assert spy["momentum_12_1"].reason == "unavailable"
    assert spy["beta_252d"].reason == spy["relative_momentum_12_1"].reason == "not_meaningful"


def test_close_against_its_averages() -> None:
    values = [100.0] * 199 + [120.0]
    found = by_id(price_measures(DEFINITIONS, T, series("AAPL", values), None)[0])
    # 50-session mean 100.4, 200-session mean 100.1
    assert found["close_vs_sma_50"].value == Decimal("19.52")
    assert found["close_vs_sma_200"].value == Decimal("19.88")


def test_volatility_of_daily_total_returns_annualized() -> None:
    values = [100.0 if i % 2 == 0 else 101.0 for i in range(61)]
    found = by_id(price_measures(DEFINITIONS, T, series("AAPL", values), None)[0])
    returns = [(values[i] / values[i - 1]) - 1 for i in range(1, 61)]
    mean = sum(returns) / len(returns)
    sd = math.sqrt(sum((r - mean) ** 2 for r in returns) / (len(returns) - 1))
    assert found["volatility_60d"].value == Decimal(str(round(sd * math.sqrt(252) * 100, 2)))


def test_total_returns_reinvest_dividends_on_the_ex_date() -> None:
    values = [100.0] * 30
    ex = sessions(30)[-10]
    paid = series("TLT", values, dividends=[Dividend(ex, Decimal("1"), False)])
    found = by_id(price_measures(DEFINITIONS, T, paid, None)[0])
    assert found["reversal_1m"].value == Decimal("1.00")  # flat price, one 1.00 dividend
    dividends = next(i for i in found["reversal_1m"].inputs if i.name == "dividends")
    assert (dividends.value, dividends.note) == (Decimal(1), "1 ex-date reinvested at the close")
    # a dividend not yet public at T is not counted
    future = series(
        "TLT", values, dividends=[Dividend(LAST + timedelta(days=3), Decimal("1"), False)]
    )
    assert by_id(price_measures(DEFINITIONS, T, future, None)[0])["reversal_1m"].value == 0


def test_closes_and_dividends_move_to_the_split_basis_of_t() -> None:
    days = sessions(30)
    split = Split(days[20], Decimal(1), Decimal(4))  # 4-for-1, effective from day 20
    raw = [100.0] * 20 + [25.0] * 10  # the raw close falls by 4: no economic change
    paid = Dividend(days[10], Decimal("0.4"), False)  # pre-split, per old share
    evidence = Series("NVDA", closes(raw), [split], [paid])
    moved = known_closes(evidence.closes, T, evidence.splits)
    assert {c.close for c in moved} == {Decimal(25)}
    assert known_dividends(evidence.dividends, T, evidence.splits)[0].rate == Decimal("0.1")
    found = by_id(price_measures(DEFINITIONS, T, evidence, None)[0])
    assert found["reversal_1m"].value == Decimal("0.40")  # 0.1 on 25: the dividend only
    # As known before the split, nothing moves.
    before = end_of_day(days[15])
    assert {c.close for c in known_closes(evidence.closes, before, evidence.splits)} == {
        Decimal(100)
    }


def test_a_dividend_and_a_split_on_the_same_ex_date() -> None:
    days = sessions(25)
    split = Split(days[-5], Decimal(1), Decimal(2))
    paid = Dividend(days[-5], Decimal("1"), False)  # per new share: the split is effective first
    evidence = Series("XLK", closes([100.0] * 20 + [50.0] * 5), [split], [paid])
    assert known_dividends(evidence.dividends, T, evidence.splits)[0].rate == Decimal(1)
    found = by_id(price_measures(DEFINITIONS, T, evidence, None)[0])
    assert found["reversal_1m"].value == Decimal("2.00")


def test_relative_momentum_and_beta_against_the_benchmark() -> None:
    spy = series("SPY", [100.0] * 260)  # flat: its returns never vary
    stock = series("AAPL", growing(260, 0.001))
    found = by_id(price_measures(DEFINITIONS, T, stock, spy)[0])
    own, theirs = (
        found["momentum_12_1"].value,
        by_id(price_measures(DEFINITIONS, T, spy, None)[0])["momentum_12_1"].value,
    )
    assert own is not None and theirs is not None
    assert found["relative_momentum_12_1"].value == own - theirs
    assert found["beta_252d"].reason == "unavailable"
    assert found["beta_252d"].detail == "SPY returns did not vary"
    # The benchmark itself: not meaningful.
    benchmark = by_id(price_measures(DEFINITIONS, T, spy, spy)[0])
    assert benchmark["relative_momentum_12_1"].reason == "not_meaningful"
    assert benchmark["beta_252d"].reason == "not_meaningful"


def test_beta_is_the_slope_of_returns_on_the_benchmark() -> None:
    wiggle = [100.0 * (1 + (0.01 if i % 3 == 0 else -0.004)) ** (i % 7) for i in range(260)]
    doubled = [100.0 * (1 + 2 * (v / 100.0 - 1)) for v in wiggle]
    spy, stock = series("SPY", wiggle), series("AAPL", doubled)
    beta = by_id(price_measures(DEFINITIONS, T, stock, spy)[0])["beta_252d"].value
    assert beta is not None and Decimal("1.5") < beta < Decimal("2.5")


def test_relative_needs_the_same_closes() -> None:
    spy = Series("SPY", closes([100.0] * 260, LAST - timedelta(days=7)), [], [])
    found = by_id(price_measures(DEFINITIONS, T, series("AAPL", [100.0] * 260), spy)[0])
    assert found["relative_momentum_12_1"].reason == "unavailable"
    assert "differs" in found["relative_momentum_12_1"].detail


def test_dividend_gaps() -> None:
    quarterly = [date(2024, 3, 15), date(2024, 6, 14), date(2024, 12, 13), date(2025, 3, 14)]
    paid = [Dividend(d, Decimal(1), False) for d in quarterly]
    since, ratio = date(2016, 1, 1), Decimal("1.25")
    notes = dividend_gaps(paid, date(2024, 7, 1), date(2025, 3, 31), since, ratio)
    assert notes == [
        "no dividend recorded between 2024-06-14 and 2024-12-13 (usually every 91 days)"
    ]
    assert dividend_gaps(paid, date(2025, 1, 1), date(2025, 3, 31), since, ratio) == []
    trailing = dividend_gaps(paid, date(2025, 1, 1), date(2025, 8, 1), since, ratio)
    assert trailing == ["no dividend recorded since 2025-03-14 (usually every 91 days)"]
    early = [
        Dividend(d, Decimal(1), False)
        for d in (date(2016, 6, 17), date(2016, 9, 16), date(2016, 12, 16), date(2017, 3, 17))
    ]
    assert dividend_gaps(early, date(2016, 1, 4), date(2016, 12, 30), since, ratio) == [
        "no dividend recorded before 2016-06-17 (history from 2016-01-01)"
    ]
    # too few payments to know the usual interval; specials are not regular payments
    assert dividend_gaps(paid[:3], date(2024, 1, 1), date(2025, 3, 31), since, ratio) == []


def test_total_returns_ignore_dividends_before_the_first_close() -> None:
    days = sessions(3)
    found = total_returns(closes([100.0, 100.0, 100.0]), [Dividend(days[0], Decimal(5), False)])
    assert found.paid == [0, 0, 0]


@pytest.mark.parametrize("bad", [{"to_sessions": 252, "from_sessions": 21}])
def test_momentum_windows_must_be_ordered(bad: dict[str, int]) -> None:
    content = DEFINITIONS.content()
    content["price"]["momentum_12_1"] = bad  # type: ignore[index]
    with pytest.raises(ValueError, match="fewer than"):
        type(DEFINITIONS).model_validate(content)


def test_feed_status_and_last_close() -> None:
    _, last = price_measures(DEFINITIONS, T, series("AAPL", [100.0] * 5), None)
    assert last is not None and (last.day, last.feed_status) == (LAST, "end_of_day")
    nothing = price_measures(
        DEFINITIONS, datetime(2010, 1, 1, tzinfo=UTC), series("AAPL", [1.0]), None
    )
    assert nothing[1] is None and nothing[0][0].detail == "no close known at this time"


def test_a_relative_measure_names_the_benchmark_notes() -> None:
    from autotrading.api.factors import _attributed

    own = Measure(
        measure_id="momentum_12_1",
        group="trend",
        unit="percent",
        value=Decimal(1),
        detail="",
        notes=["no dividend recorded between 2025-12-19 and 2026-02-02 (usually every 30 days)"],
    )
    relative = Measure(
        measure_id="relative_momentum_12_1",
        group="relative",
        unit="percent",
        value=Decimal(1),
        detail="",
        notes=[*own.notes, "no dividend recorded since 2026-06-18 (usually every 91 days)"],
    )
    found = _attributed([own, relative], "SPY")[1].notes
    assert found == [
        own.notes[0],
        "SPY: no dividend recorded since 2026-06-18 (usually every 91 days)",
    ]
