"""Backtests (M2.5, ADR-033): fills after T, costs, splits, dividends, turnover, holding periods,
folds around the rule release, the reference limits, and performance always withheld."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from autotrading.domain.backtest import (
    WITHHELD,
    BacktestRulesFile,
    Event,
    Instrument,
    Kind,
    Limits,
    equal_weights,
    fill_day,
    run,
    sessions,
)
from autotrading.domain.factors import Dividend
from autotrading.domain.momentum import (
    MomentumRulesFile,
    PreviousMomentum,
    assess,
    daily,
    momentum_alert,
    signals,
)
from autotrading.domain.provenance import end_of_day
from autotrading.domain.risk import Bar
from autotrading.domain.rotation import MeasureInput, SnapshotInput
from autotrading.domain.splits import Split
from autotrading.settings import get_settings

CONFIG = Path(get_settings().resolved_config_dir())
FILE = BacktestRulesFile.model_validate(
    yaml.safe_load((CONFIG / "backtest_rules.yaml").read_text())
)
RULES = FILE.active()
MOMENTUM_FILE = MomentumRulesFile.model_validate(
    yaml.safe_load((CONFIG / "momentum_rules.yaml").read_text())
)
MOMENTUM = MOMENTUM_FILE.active()
# A released version never changes (ADR-033): a new rule_version is the only way to edit one.
PINNED = {
    "0.1.0": "fdc474b9574949ab32e94234bd7c8c36f53a2ad9c0d16408be23d78ec5ef16e4",
    # S3 on rotation 0.2.0 and S4 from its stored daily assessments (ADR-036)
    "0.2.0": "f7aff03a644230f4f6b64fa805623095bf9dabdb1066a51ebd403a02a31f5af0",
}
MOMENTUM_PINNED = {"0.1.0": "26dd4e8db014c82b87537c1f07db596f166620a734af60042dd60dda2fe373d1"}
LIMITS = Limits(
    rule_version="0.1.0",
    position_pct=Decimal(10),
    sector_pct=Decimal(30),
    gross_pct=Decimal(100),
    volume_pct=Decimal(1),
    volume_sessions=3,
    unlimited_sectors=frozenset({"broad_market"}),
)


def days(start: date, count: int) -> list[date]:
    out: list[date] = []
    day = start
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


DAYS = days(date(2026, 9, 28), 30)  # 2026-09-28 .. 2026-11-06


def bars(prices: list[float], volume: int = 1_000_000) -> list[Bar]:
    return [
        Bar(d, Decimal(str(p)), Decimal(volume), "end_of_day", end_of_day(d))
        for d, p in zip(DAYS, prices, strict=False)
    ]


def instrument(
    symbol: str,
    prices: list[float],
    kind: Kind = "equity",
    sector: str | None = None,
    volume: int = 1_000_000,
    splits: tuple[Split, ...] = (),
    dividends: tuple[Dividend, ...] = (),
) -> Instrument:
    return Instrument(symbol, kind, bars(prices, volume), splits, dividends, sector)


def market(**extra: Instrument) -> dict[str, Instrument]:
    flat = [100.0] * len(DAYS)
    return {
        "SPY": instrument("SPY", flat, "etf", sector="broad_market"),
        "AAA": instrument("AAA", [10.0 + i for i in range(len(DAYS))], sector="tech"),
        "BBB": instrument("BBB", flat, sector="energy"),
        **extra,
    }


END = end_of_day(DAYS[-1])
MONTH_END = end_of_day(date(2026, 9, 30))  # DAYS[2]


def event(at: datetime, weights: dict[str, str], reason: str = "month_start") -> Event:
    return Event(at, {k: Decimal(v) for k, v in weights.items()}, reason, {"table": "t", "id": "1"})


def test_the_rule_sets_are_pinned() -> None:
    assert {r.rule_version: r.rule_set().content_sha256() for r in FILE.rule_sets} == PINNED
    assert {r.rule_version: r.rule_set().content_sha256() for r in MOMENTUM_FILE.rule_sets} == (
        MOMENTUM_PINNED
    )
    assert (RULES.costs.bps("equity", "base"), RULES.costs.bps("etf", "base")) == (7, 3)
    assert (RULES.costs.bps("equity", "double"), RULES.costs.bps("etf", "double")) == (14, 6)
    assert set(RULES.strategies) == {"S1", "S3", "S4"}
    assert RULES.rule_version == "0.2.0"
    assert (RULES.strategies["S3"].rule_version, RULES.strategies["S4"].targets_from) == (
        "0.2.0",
        "momentum_assessments",
    )
    first = next(r.rule_set() for r in FILE.rule_sets if r.rule_version == "0.1.0")
    assert first.strategies["S4"].targets_from == "factor_snapshots"


def test_a_target_fills_at_the_first_close_published_after_t() -> None:
    calendar = sessions(market()["SPY"], END)
    # a month-end target is known at the end of that session: its own close is never used
    assert fill_day(calendar, MONTH_END) == date(2026, 10, 1)
    # a target known before a session's close fills at that close
    assert fill_day(calendar, MONTH_END + timedelta(hours=1)) == date(2026, 10, 1)
    result = run(RULES, "S4", END, [event(MONTH_END, {"AAA": "100"})], market(), None)
    trade = result.trades[0]
    assert (trade.day, trade.symbol, trade.side, trade.price) == (
        date(2026, 10, 1),
        "AAA",
        "buy",
        13,
    )
    assert result.start == date(2026, 10, 1)


def test_costs_are_charged_per_side_by_instrument_type_and_scenario() -> None:
    result = run(RULES, "S4", END, [event(MONTH_END, {"AAA": "50", "SPY": "50"})], market(), None)
    by = {t.symbol: t for t in result.trades}
    assert (by["AAA"].cost_bps, by["SPY"].cost_bps) == (7, 3)
    rebalance = result.rebalances[0]
    # buying 100% from cash: half at 7 bps and half at 3 bps of the portfolio
    assert rebalance.cost_bps == pytest.approx(Decimal(5), abs=Decimal("0.01"))
    assert rebalance.turnover_pct == pytest.approx(Decimal(100), abs=Decimal("0.1"))
    base, double = result.scenarios
    assert (base.scenario, double.scenario) == ("base", "double")
    assert double.cost_bps == pytest.approx(base.cost_bps * 2, abs=Decimal("0.01"))


def test_switching_holdings_turns_over_twice_and_records_holding_periods() -> None:
    later = end_of_day(DAYS[10])
    result = run(
        RULES,
        "S4",
        END,
        [event(MONTH_END, {"AAA": "100"}), event(later, {"BBB": "100"})],
        market(),
        None,
    )
    second = result.rebalances[1]
    assert second.fill_day == DAYS[11]
    assert second.turnover_pct == pytest.approx(Decimal(200), abs=Decimal("0.5"))
    sides = [(t.symbol, t.side) for t in result.trades if t.day == DAYS[11]]
    assert sides == [("AAA", "sell"), ("BBB", "buy")]
    closed = next(p for p in result.positions if p.symbol == "AAA")
    # held from the close of 10-01 to the close of 10-13: eight sessions
    assert (closed.entry, closed.exit, closed.sessions) == (date(2026, 10, 1), DAYS[11], 8)
    still = next(p for p in result.positions if p.symbol == "BBB")
    assert still.exit is None


def test_a_split_multiplies_the_shares_without_a_trade() -> None:
    prices = [100.0] * 5 + [50.0] * (len(DAYS) - 5)  # 2-for-1 on DAYS[5]
    split = instrument(
        "CCC", prices, sector="tech", splits=(Split(DAYS[5], Decimal(1), Decimal(2)),)
    )
    later = end_of_day(DAYS[8])
    result = run(
        RULES,
        "S4",
        END,
        [event(MONTH_END, {"CCC": "50"}), event(later, {"CCC": "50"})],
        market(CCC=split),
        None,
    )
    # half held through the split: still about half, so the second target trades nothing
    assert [t.day for t in result.trades if t.symbol == "CCC"] == [date(2026, 10, 1)]
    assert result.rebalances[1].turnover_pct < 1


def test_a_dividend_goes_to_cash_until_the_next_target() -> None:
    dividend = Dividend(DAYS[6], Decimal(5), False)  # 5% of a flat 100 close
    paying = instrument("DDD", [100.0] * len(DAYS), sector="energy", dividends=(dividend,))
    later = end_of_day(DAYS[10])
    result = run(
        RULES,
        "S4",
        END,
        [event(MONTH_END, {"DDD": "100"}), event(later, {"DDD": "100"})],
        market(DDD=paying),
        None,
    )
    # the cash dividend is reinvested at the next target
    buy = [t for t in result.trades if t.day == DAYS[11]]
    assert len(buy) == 1 and buy[0].side == "buy"
    assert buy[0].weight_before == pytest.approx(Decimal("95.24"), abs=Decimal("0.05"))
    assert result.scenarios[0].folds[0].average_gross_pct < 100


def test_folds_are_calendar_years_split_at_the_rule_release() -> None:
    result = run(RULES, "S4", END, [event(MONTH_END, {"AAA": "100"})], market(), None)
    # S4's rules were released on 2026-10-17: the rest of 2026 is out-of-sample
    folds = result.scenarios[0].folds
    assert [(f.label, f.sample) for f in folds] == [
        ("2026 in-sample", "in_sample"),
        ("2026 out-of-sample", "out_of_sample"),
    ]
    assert folds[0].end == date(2026, 10, 16) and folds[1].start == date(2026, 10, 19)
    assert folds[0].rebalances == 1 and folds[1].rebalances == 0


def test_a_target_without_a_close_on_the_fill_day_stays_in_cash() -> None:
    late = Instrument("EEE", "equity", bars([10.0] * len(DAYS))[5:], sector="tech")
    result = run(
        RULES, "S4", END, [event(MONTH_END, {"EEE": "50", "AAA": "50"})], market(EEE=late), None
    )
    assert result.rebalances[0].skipped == ["EEE"]
    assert [t.symbol for t in result.trades] == ["AAA"]


def test_targets_are_compared_with_the_risk_limits_for_reference() -> None:
    thin = instrument("FFF", [10.0] * len(DAYS), sector="tech", volume=100)
    result = run(
        RULES,
        "S4",
        END,
        [event(MONTH_END, {"AAA": "40", "FFF": "20", "SPY": "40"})],
        market(FFF=thin),
        LIMITS,
    )
    vetoes = {(v.limit, v.subject) for v in result.rebalances[0].vetoes}
    assert vetoes == {
        ("position", "AAA"),
        ("position", "FFF"),
        ("position", "SPY"),
        ("sector", "tech"),  # 60% of tech; SPY is broad market, outside the sector limit
        ("volume", "FFF"),  # 20% of 100,000 at 10 a share is 2,000 shares against 100 a day
    }
    # trades still follow the strategy: the limits are a reference only (B6)
    assert {t.symbol for t in result.trades} == {"AAA", "FFF", "SPY"}


def test_performance_is_always_withheld() -> None:
    result = run(RULES, "S4", END, [event(MONTH_END, {"AAA": "100"})], market(), None)
    assert [w.metric for w in result.withheld] == list(WITHHELD)
    assert all(w.value is None for w in result.withheld)
    document = result.model_dump(mode="json")
    text = str(document).lower()
    for word in ("equity_curve", "'return", "cagr': '", "sharpe': '", "value_pct"):
        assert word not in text


def test_the_same_inputs_give_the_same_document() -> None:
    events = [
        event(MONTH_END, {"AAA": "50", "BBB": "50"}),
        event(end_of_day(DAYS[12]), {"AAA": "100"}),
    ]
    one = run(RULES, "S3", END, events, market(), LIMITS).model_dump(mode="json")
    two = run(RULES, "S3", END, events, market(), LIMITS).model_dump(mode="json")
    assert one == two


def test_equal_weights_round_down() -> None:
    assert equal_weights(["A", "B", "C"]) == {s: Decimal("33.33") for s in "ABC"}
    assert equal_weights([]) == {}


# ---------- S4 (medium-term momentum) ----------


def snapshot(symbol: str, at: datetime, **values: str | None) -> SnapshotInput:
    base: dict[str, str | None] = {"momentum_12_1": "10", "relative_momentum_12_1": "2"}
    base.update(values)
    return SnapshotInput(
        id=f"snap-{symbol}",
        symbol=symbol,
        known_at=at,
        definition_version="0.1.0",
        last_close=at.date(),
        feed_status="end_of_day",
        measures={
            k: MeasureInput(None if v is None else Decimal(v), "unavailable" if v is None else "ok")
            for k, v in base.items()
        },
    )


def test_s4_holds_each_company_above_both_thresholds_in_equal_weights() -> None:
    snaps = {s: snapshot(s, MONTH_END) for s in MOMENTUM.universe}
    snaps["AAPL"] = snapshot("AAPL", MONTH_END, momentum_12_1="0")  # exactly 0 is not above
    snaps["MSFT"] = snapshot("MSFT", MONTH_END, relative_momentum_12_1="-0.01")
    snaps["NVDA"] = snapshot("NVDA", MONTH_END, momentum_12_1=None)
    snaps["JPM"] = snapshot("JPM", MONTH_END - timedelta(days=6))  # stale
    del snaps["XOM"]
    result = assess(MOMENTUM, MONTH_END, snaps)
    assert list(result.target) == ["GOOGL", "META", "AZO", "ORLY", "LOW"]
    assert set(result.target.values()) == {Decimal("20.00")}
    by = {r.symbol: r for r in result.readings}
    assert by["AAPL"].detail == "not selected: momentum_12_1"
    assert by["MSFT"].detail == "not selected: relative_momentum_12_1"
    assert by["NVDA"].conditions[0].status == "unavailable"
    assert "older than 5 days" in by["JPM"].detail
    assert by["XOM"].detail == "no factor snapshot known at T"
    assert result.cash_pct == 0


# ---------- S4 daily (M3.0, ADR-036 D7) ----------


def everyone(at: datetime) -> dict[str, SnapshotInput]:
    return {s: snapshot(s, at) for s in MOMENTUM.universe}


def test_s4_daily_sets_a_target_at_the_first_assessment_of_each_month() -> None:
    first = end_of_day(date(2026, 10, 1))
    start = daily(MOMENTUM, first, everyone(first), None)
    assert (start.reason, start.rebalance, start.set_at) == ("month_start", True, first)
    assert start.target == assess(MOMENTUM, first, everyone(first)).target
    held = PreviousMomentum("m-1", first, start.target or {}, first)
    # later in the month the target is carried, whatever the readings say
    later = end_of_day(date(2026, 10, 15))
    snaps = everyone(later) | {"AAPL": snapshot("AAPL", later, momentum_12_1="-5")}
    carried = daily(MOMENTUM, later, snaps, held)
    assert (carried.reason, carried.rebalance, carried.set_at) == ("carried", False, first)
    assert carried.target == start.target and carried.previous_id == "m-1"
    assert carried.detail == "target of 2026-10-01 carried"
    assert next(r for r in carried.readings if r.symbol == "AAPL").selected is False
    # the next New York month sets a new one
    november = end_of_day(date(2026, 11, 2))
    renewed = daily(MOMENTUM, november, snaps | everyone(november), held)
    assert (renewed.reason, renewed.set_at) == ("month_start", november)


def test_s4_daily_is_unavailable_without_a_fresh_snapshot() -> None:
    at = end_of_day(date(2026, 10, 15))
    stale = {s: snapshot(s, at - timedelta(days=9)) for s in MOMENTUM.universe}
    result = daily(MOMENTUM, at, stale, None)
    assert (result.reason, result.target, result.cash_pct, result.rebalance) == (
        "unavailable",
        None,
        None,
        False,
    )
    assert signals(result, "m-2", at) == []


def test_s4_signals_cite_the_assessment_and_the_snapshot_once_per_company_held() -> None:
    at = end_of_day(date(2026, 10, 1))
    snaps = everyone(at) | {"XOM": snapshot("XOM", at, momentum_12_1="-1")}
    result = daily(MOMENTUM, at, snaps, None)
    found = signals(result, "m-3", at + timedelta(days=1))
    assert [s for s, _ in found] == [s for s in MOMENTUM.universe if s != "XOM"]
    _, first = found[0]
    assert (first.family_id, first.strategy_id, first.rule_version) == (5, "S4", "0.1.0")
    assert first.observation_ids == [
        {"table": "momentum_assessments", "id": "m-3"},
        {"table": "factor_snapshots", "id": "snap-AAPL"},
    ]
    assert (first.score, first.evidence_independence) == (Decimal("10"), 2)
    assert first.execution_eligibility == "paper_only" and first.backfilled
    carried = daily(MOMENTUM, at + timedelta(days=3), snaps, PreviousMomentum("m-3", at, {}, at))
    assert signals(carried, "m-4", at) == []


def test_s4_alerts_a_changed_target_only() -> None:
    at = end_of_day(date(2026, 10, 1))
    snaps = everyone(at) | {"XOM": snapshot("XOM", at, momentum_12_1="-1")}
    result = daily(MOMENTUM, at, snaps, None)
    previous = {"XOM": Decimal("50.00"), "AAPL": Decimal("50.00")}
    found = momentum_alert(result, previous, "m-5")
    assert found is not None
    assert (found.kind, found.level, found.source_key) == ("momentum", 0, "momentum:m-5")
    assert found.direction == "down"  # nine at 11.11% invest 99.99%, against 100% before
    assert found.title.startswith("S4 momentum (monthly target): now AAPL, MSFT")
    assert found.title.endswith("(was AAPL, XOM)")  # universe order
    assert found.evidence[0]["table"] == "momentum_assessments"
    # a target read back from JSONB (keys in JSONB order) still reads in universe order
    target = list((result.target or {}).items())
    jumbled = result.model_copy(update={"target": dict(reversed(target))})
    again = momentum_alert(jumbled, previous, "m-9")
    assert again is not None and again.title == found.title
    # the same target, a carried one or no previous target: no alert
    assert momentum_alert(result, dict(result.target or {}), "m-6") is None
    assert momentum_alert(result, None, "m-7") is None
    carried = daily(MOMENTUM, at + timedelta(days=3), snaps, PreviousMomentum("m-5", at, {}, at))
    assert momentum_alert(carried, previous, "m-8") is None
