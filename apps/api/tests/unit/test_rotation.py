"""S3 ETF rotation (M2.4, ADR-032): every gate, threshold boundary and rebalance rule."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from autotrading.domain.provenance import end_of_day
from autotrading.domain.rotation import (
    REGIME_FAMILY,
    TREND_FAMILY,
    MeasureInput,
    PreviousTarget,
    RegimeInput,
    RotationRulesFile,
    SnapshotInput,
    StressState,
    assess,
    rotation_alert,
    signals,
)
from autotrading.settings import get_settings

FILE = RotationRulesFile.model_validate(
    yaml.safe_load(Path(get_settings().resolved_config_dir() / "rotation_rules.yaml").read_text())
)
RULES = FILE.active()
# A released version never changes (ADR-032): a new rule_version is the only way to edit one.
PINNED = {"0.1.0": "88eebb93f5e1e4e3affd567c5e06fa79190669c152dd6d0bdcf8b4a8fef04866"}
T = end_of_day(date(2026, 9, 30))  # a month end
UP = {"momentum_12_1": "10", "close_vs_sma_200": "5", "beta_252d": "0.9"}


def regime(stress: StressState | None, at: datetime = T) -> RegimeInput:
    return RegimeInput(
        id="regime-1",
        known_at=at,
        rule_version="0.1.0",
        stress=stress,
        quadrant="goldilocks",
        stress_detail="test",
    )


def snapshot(symbol: str, at: datetime = T, **values: str | None) -> SnapshotInput:
    merged = {**UP, **values}
    return SnapshotInput(
        id=f"snap-{symbol}",
        symbol=symbol,
        known_at=at,
        definition_version="0.1.0",
        last_close=at.date(),
        feed_status="end_of_day",
        measures={
            k: MeasureInput(None if v is None else Decimal(v), "unavailable" if v is None else "ok")
            for k, v in merged.items()
        },
    )


def everything_up(at: datetime = T) -> dict[str, SnapshotInput]:
    return {s: snapshot(s, at) for s in RULES.sleeves.universe()}


def held(rotation_target: object) -> list[str]:
    assert isinstance(rotation_target, list)
    return [h.symbol for h in rotation_target]


def previous(target: dict[str, str], at: datetime, stress: StressState | None) -> PreviousTarget:
    return PreviousTarget(
        id="prev-1",
        known_at=at,
        stress=stress,
        target={k: Decimal(v) for k, v in target.items()},
        set_at=at,
    )


def test_the_active_rule_set_is_pinned() -> None:
    assert {r.rule_version: r.rule_set().content_sha256() for r in FILE.rule_sets} == PINNED
    assert RULES.sleeves.universe() == ["SPY", "QQQ", "IWM", "XLK", "XLE", "TLT", "IEF", "GLD"]


def test_normal_holds_every_etf_in_trend_in_equal_weights() -> None:
    result = assess(RULES, T, regime("normal"), everything_up(), None)
    assert result.reason == "month_start" and result.rebalance
    assert held(result.target) == RULES.sleeves.universe()
    assert {h.weight_pct for h in result.target or []} == {Decimal("12.50")}
    assert result.cash_pct == Decimal("0.00")


def test_weights_round_down_and_the_rest_is_cash() -> None:
    snaps = everything_up()
    for s in ["IWM", "XLK", "XLE", "TLT", "IEF"]:
        snaps[s] = snapshot(s, momentum_12_1="-1")
    result = assess(RULES, T, regime("normal"), snaps, None)
    assert held(result.target) == ["SPY", "QQQ", "GLD"]
    assert {h.weight_pct for h in result.target or []} == {Decimal("33.33")}
    assert result.cash_pct == Decimal("0.01")


@pytest.mark.parametrize(
    ("stress", "expected"),
    [
        ("normal", ["SPY", "QQQ", "IWM", "XLK", "XLE", "TLT", "IEF", "GLD"]),
        ("elevated", ["SPY", "XLE", "TLT", "IEF", "GLD"]),  # no beta >= 1.10
        ("high", ["TLT", "IEF", "GLD"]),
        ("crisis", ["TLT", "IEF", "GLD"]),
    ],
)
def test_each_stress_state_gates_the_sleeves(stress: StressState, expected: list[str]) -> None:
    snaps = everything_up()
    for s in ["QQQ", "IWM", "XLK"]:
        snaps[s] = snapshot(s, beta_252d="1.4")
    result = assess(RULES, T, regime(stress), snaps, None)
    assert held(result.target) == expected


def test_beta_at_the_threshold_is_high_and_the_benchmark_counts_as_one() -> None:
    snaps = everything_up()
    snaps["QQQ"] = snapshot("QQQ", beta_252d="1.10")
    snaps["IWM"] = snapshot("IWM", beta_252d="1.09")
    snaps["XLK"] = snapshot("XLK", beta_252d=None)  # unknown beta counts as high
    snaps["SPY"] = snapshot("SPY", beta_252d=None)  # the benchmark: 1.00
    result = assess(RULES, T, regime("elevated"), snaps, None)
    by = {r.symbol: r for r in result.readings}
    assert by["QQQ"].high_beta and not by["QQQ"].allowed
    assert not by["IWM"].high_beta and by["IWM"].allowed
    assert by["XLK"].high_beta and by["XLK"].detail == "beta unavailable (high beta)"
    assert by["SPY"].beta == Decimal("1.00") and by["SPY"].allowed


def test_a_trend_measure_at_zero_is_not_up() -> None:
    snaps = everything_up()
    snaps["SPY"] = snapshot("SPY", momentum_12_1="0")
    snaps["QQQ"] = snapshot("QQQ", close_vs_sma_200="0")
    snaps["IWM"] = snapshot("IWM", close_vs_sma_200="0.01")
    result = assess(RULES, T, regime("normal"), snaps, None)
    by = {r.symbol: r for r in result.readings}
    assert not by["SPY"].trend_up and by["SPY"].detail == "trend not up: momentum_12_1"
    assert not by["QQQ"].trend_up
    assert by["IWM"].trend_up


def test_missing_stale_or_unavailable_inputs_are_not_selected_with_the_reason() -> None:
    snaps = everything_up()
    del snaps["SPY"]
    snaps["QQQ"] = snapshot("QQQ", at=T - timedelta(days=6))
    snaps["IWM"] = snapshot("IWM", momentum_12_1=None)
    result = assess(RULES, T, regime("normal"), snaps, None)
    by = {r.symbol: r for r in result.readings}
    assert by["SPY"].detail == "no factor snapshot known at T"
    assert "older than 5 days" in by["QQQ"].detail
    assert by["IWM"].trend[0].status == "unavailable" and not by["IWM"].eligible
    assert "SPY" not in held(result.target)


def test_nothing_in_trend_is_all_cash() -> None:
    snaps = {s: snapshot(s, momentum_12_1="-5") for s in RULES.sleeves.universe()}
    result = assess(RULES, T, regime("normal"), snaps, None)
    assert result.target == [] and result.cash_pct == Decimal(100)
    assert result.detail == "first assessment of the month: cash only"


def test_no_or_stale_regime_is_unavailable_without_a_target() -> None:
    for found in (None, regime("normal", at=T - timedelta(days=4)), regime(None)):
        result = assess(RULES, T, found, everything_up(), None)
        assert result.reason == "unavailable" and result.target is None
        assert signals(result, "a-1", T) == []


def test_the_target_is_carried_within_a_month() -> None:
    before = previous({"SPY": "50.00", "TLT": "50.00"}, T - timedelta(days=3), "normal")
    later = T - timedelta(days=1)  # same New York month
    result = assess(RULES, later, regime("normal", later), everything_up(later), before)
    assert result.reason == "carried" and not result.rebalance
    assert held(result.target) == ["SPY", "TLT"]
    assert result.set_at == before.set_at
    assert signals(result, "a-1", later) == []


def test_a_new_month_sets_a_new_target() -> None:
    before = previous({"SPY": "100.00"}, T - timedelta(days=31), "normal")
    result = assess(RULES, T, regime("normal"), everything_up(), before)
    assert result.reason == "month_start"
    assert len(held(result.target)) == 8


def test_rising_into_high_switches_to_defensive_at_once_and_easing_waits() -> None:
    mid = end_of_day(date(2026, 9, 15))
    before = previous({"SPY": "50.00", "QQQ": "50.00"}, mid - timedelta(days=1), "elevated")
    switched = assess(RULES, mid, regime("high", mid), everything_up(mid), before)
    assert switched.reason == "defensive_switch" and switched.rebalance
    assert held(switched.target) == ["TLT", "IEF", "GLD"]
    # still high the next day: carried, no new switch
    after = previous({"TLT": "33.33", "IEF": "33.33", "GLD": "33.33"}, mid, "high")
    nxt = mid + timedelta(days=1)
    still = assess(RULES, nxt, regime("crisis", nxt), everything_up(nxt), after)
    assert still.reason == "carried"
    # easing back to normal within the month keeps the defensive target until the month ends
    eased = assess(RULES, nxt, regime("normal", nxt), everything_up(nxt), after)
    assert eased.reason == "carried" and held(eased.target) == ["TLT", "IEF", "GLD"]


def test_a_new_target_makes_two_paper_signals_per_etf() -> None:
    snaps = {s: snapshot(s, momentum_12_1="-1") for s in RULES.sleeves.universe()}
    snaps["XLE"] = snapshot("XLE", momentum_12_1="56.04")
    result = assess(RULES, T, regime("normal"), snaps, None)
    made = signals(result, "a-1", T + timedelta(hours=1))
    assert [(s, x.family_id) for s, x in made] == [("XLE", TREND_FAMILY), ("XLE", REGIME_FAMILY)]
    trend, gate = made[0][1], made[1][1]
    assert trend.strategy_id == gate.strategy_id == "S3"
    assert trend.direction == "long" and trend.execution_eligibility == "paper_only"
    assert trend.score == Decimal("56.04") and trend.evidence_independence == 2
    assert trend.observation_ids[1] == {"table": "factor_snapshots", "id": "snap-XLE"}
    assert gate.observation_ids[1] == {"table": "regime_assessments", "id": "regime-1"}
    assert trend.backfilled


def test_a_changed_target_raises_an_alert_with_its_direction() -> None:
    before = previous({"SPY": "50.00", "QQQ": "50.00"}, T - timedelta(days=1), "elevated")
    mid = T  # September 30, the same New York month as the previous day
    switched = assess(RULES, mid, regime("high", mid), everything_up(mid), before)
    alert = rotation_alert(switched, before.target, "a-1")
    assert alert is not None and alert.kind == "rotation" and alert.direction == "down"
    assert alert.title.startswith("S3 rotation (defensive switch): now TLT, IEF, GLD")
    assert alert.title.endswith("(was SPY, QQQ)")
    same = assess(
        RULES,
        T,
        regime("normal"),
        everything_up(),
        previous({s: "12.50" for s in RULES.sleeves.universe()}, T - timedelta(days=31), "normal"),
    )
    assert (
        rotation_alert(same, {s: Decimal("12.50") for s in RULES.sleeves.universe()}, "a") is None
    )
    assert rotation_alert(same, None, "a") is None


def test_the_same_inputs_give_the_same_document() -> None:
    one = assess(RULES, T, regime("elevated"), everything_up(), None)
    two = assess(RULES, T, regime("elevated"), everything_up(), None)
    assert one.model_dump(mode="json") == two.model_dump(mode="json")


def test_the_alert_lists_the_previous_target_in_universe_order() -> None:
    # A stored target is JSONB, whose keys come back sorted by length and then alphabetically.
    stored = {"IWM": Decimal("50.00"), "SPY": Decimal("25.00"), "XLE": Decimal("25.00")}
    result = assess(
        RULES,
        T,
        regime("normal"),
        everything_up(),
        previous({"SPY": "100.00"}, T - timedelta(days=31), "normal"),
    )
    alert = rotation_alert(result, stored, "a-1")
    assert alert is not None and alert.title.endswith("(was SPY, IWM, XLE)")
