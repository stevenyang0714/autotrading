"""Macro regime and market stress rules (M2.1, ADR-029)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from autotrading.domain.regime import (
    Bar,
    Obs,
    RegimeRulesFile,
    assess,
    correlation,
    credit,
    drawdown,
    growth,
    inflation,
    policy,
    quadrant,
    volatility,
)
from autotrading.settings import get_settings

RULES = RegimeRulesFile.model_validate(
    yaml.safe_load(Path(get_settings().resolved_config_dir() / "regime_rules.yaml").read_text())
).active()
# A released version never changes (ADR-029): a new rule_version is the only way to edit one.
PINNED = {"0.1.0": "f92d578c2b5a1a15e66ab4bdbdceaa13b5d376d11ba5f509bf88d9e9fe5ad38d"}
T = datetime(2026, 10, 6, 12, tzinfo=UTC)
VINTAGE = date(2026, 10, 2)


def monthly(values: list[float], last: date = date(2026, 9, 1)) -> list[Obs]:
    """Monthly observations ending at `last`, oldest first."""
    out = []
    for i, value in enumerate(reversed(values)):
        month = last.month - 1 - i
        out.append(
            Obs(date(last.year + month // 12, month % 12 + 1, 1), Decimal(str(value)), VINTAGE)
        )
    return list(reversed(out))


def daily(values: list[float], last: date = date(2026, 10, 5)) -> list[Obs]:
    return [
        Obs(last - timedelta(days=len(values) - 1 - i), Decimal(str(v)), VINTAGE)
        for i, v in enumerate(values)
    ]


def bars(values: list[float], last: date = date(2026, 10, 5)) -> list[Bar]:
    return [
        Bar(last - timedelta(days=len(values) - 1 - i), Decimal(str(v)))
        for i, v in enumerate(values)
    ]


def test_the_active_rule_set_is_pinned() -> None:
    assert RULES.rule_version == "0.1.0"
    assert RULES.content_sha256() == PINNED["0.1.0"]


def test_growth_states() -> None:
    steady = monthly([4.0] * 16)
    payrolls = monthly([1000, 1100, 1200, 1300])  # +100 a month
    gdp = monthly([100, 101])  # about 4% annualized
    base = {"UNRATE": steady, "PAYEMS": payrolls, "GDPC1": gdp}
    assert growth(RULES.growth, base).state == "expanding"
    slow = {**base, "PAYEMS": monthly([1000, 1050, 1100, 1150])}  # +50 a month
    assert growth(RULES.growth, slow).state == "slowing"
    sahm = {**base, "UNRATE": monthly([4.0] * 13 + [4.6, 4.7, 4.8])}
    assert growth(RULES.growth, sahm).state == "contracting"
    shrinking = {**base, "GDPC1": monthly([100, 99.5])}
    assert growth(RULES.growth, shrinking).state == "contracting"
    assert growth(RULES.growth, {}).state == "unavailable"


@pytest.mark.parametrize(
    ("latest", "state"),
    [(103.6, "hot"), (103.0, "above_target"), (102.2, "near_target"), (101.2, "below_target")],
)
def test_inflation_against_the_target(latest: float, state: str) -> None:
    core = monthly([100.0] + [100.0] * 11 + [latest])  # year on year = latest - 100
    assert inflation(RULES.inflation, {"PCEPILFE": core}).state == state


def test_inflation_direction() -> None:
    rising = monthly([100.0] * 10 + [100.2, 100.5, 101.0, 102.0])
    result = inflation(RULES.inflation, {"PCEPILFE": rising})
    assert (result.state, result.trend) == ("near_target", "rising")


def test_policy_states() -> None:
    fed = monthly([4.5])
    assert policy(RULES.policy, {"FEDFUNDS": fed}, Decimal("2.5")).state == "tight"  # real 2.0
    assert (
        policy(
            RULES.policy, {"FEDFUNDS": monthly([3.0]), "NFCI": daily([0.1])}, Decimal("2.5")
        ).state
        == "tight"
    )
    easy = policy(RULES.policy, {"FEDFUNDS": monthly([2.0]), "NFCI": daily([-0.6])}, Decimal("2.5"))
    assert easy.state == "easy"
    inverted = {"FEDFUNDS": monthly([3.0]), "T10Y2Y": daily([-0.2] * 60)}
    assert policy(RULES.policy, inverted, Decimal("2.5")).state == "tight"
    assert policy(RULES.policy, {}, None).state == "unavailable"


def test_credit_from_the_spread_or_the_nfci_credit_index() -> None:
    assert credit(RULES.credit, {"BAMLH0A0HYM2": daily([9.0])}).state == "distressed"
    jump = daily([3.0] + [3.0] * 30 + [4.2])  # +1.2 points within a month
    assert credit(RULES.credit, {"BAMLH0A0HYM2": jump}).state == "stressed"
    assert credit(RULES.credit, {"BAMLH0A0HYM2": daily([3.0])}).state == "calm"
    fallback = credit(RULES.credit, {"NFCICREDIT": daily([0.5])})
    assert (fallback.state, fallback.detail) == (
        "stressed",
        "from the NFCI credit subindex (no high-yield spread known then)",
    )
    assert credit(RULES.credit, {}).state == "unavailable"


def test_volatility_and_its_term_structure() -> None:
    assert volatility(RULES.volatility, {"VIXCLS": daily([25])}).state == "elevated"
    assert volatility(RULES.volatility, {"VIXCLS": daily([32])}).state == "stressed"
    inverted = {"VIXCLS": daily([14]), "VXVCLS": daily([13])}
    assert volatility(RULES.volatility, inverted).state == "elevated"
    assert (
        volatility(RULES.volatility, {"VIXCLS": daily([12]), "VXVCLS": daily([16])}).state == "calm"
    )


def test_quadrants() -> None:
    assert quadrant("expanding", "near_target") == "goldilocks"
    assert quadrant("expanding", "hot") == "reflation"
    assert quadrant("slowing", "above_target") == "stagflation"
    assert quadrant("contracting", "below_target") == "disinflationary_slowdown"
    assert quadrant("unavailable", "hot") is None


def test_drawdown_and_correlation() -> None:
    assert drawdown(bars([100.0] * 30 + [80.0])) == Decimal("20.00")
    assert drawdown(bars([100.0] * 5)) is None  # too short
    up = bars([100 * (1 + 0.01 * ((-1) ** i)) for i in range(70)])
    assert correlation(up, up, 60) == Decimal("1.00")
    down = bars([100 * (1 - 0.01 * ((-1) ** i)) for i in range(70)])
    assert correlation(up, down, 60) == Decimal("-1.00")
    assert correlation(up[:10], up[:10], 60) is None


def calm_series() -> dict[str, list[Obs]]:
    return {
        "UNRATE": monthly([4.0] * 16),
        "PAYEMS": monthly([1000, 1150, 1300, 1450]),
        "GDPC1": monthly([100, 101]),
        "PCEPILFE": monthly([100.0] * 12 + [102.0]),
        "FEDFUNDS": monthly([3.0]),
        "NFCI": daily([-0.4]),
        "STLFSI4": daily([-0.5]),
        "BAMLH0A0HYM2": daily([3.0] * 40),
        "VIXCLS": daily([13]),
        "VXVCLS": daily([16]),
        "DTWEXBGS": daily([120.0] * 40),
        "DCOILWTICO": daily([70.0] * 40),
    }


def test_a_calm_market_is_normal_with_every_flag_judged() -> None:
    result = assess(
        RULES, T, calm_series(), bars([100.0 + i * 0.1 for i in range(300)]), bars([90.0] * 300)
    )
    assert (result.stress, result.flags_on, result.flags_available) == ("normal", 0, 8)
    assert result.quadrant == "goldilocks"
    assert [d.state for d in result.dimensions] == [
        "expanding",
        "near_target",
        "neutral",
        "calm",
        "calm",
    ]
    # The flat TLT has no returns to correlate: that flag is not counted.
    assert (
        next(f for f in result.flags if f.flag_id == "stock_bond_selloff").status == "unavailable"
    )


def test_stress_states() -> None:
    stressed = calm_series() | {
        "NFCI": daily([0.3]),
        "STLFSI4": daily([1.5]),
        "VIXCLS": daily([25]),
        "VXVCLS": daily([22]),
    }
    spy = bars([100.0] * 260)
    result = assess(RULES, T, stressed, spy, bars([90.0] * 260))
    on = {f.flag_id for f in result.flags if f.status == "on"}
    assert on == {"nfci_tight", "stlfsi_high", "volatility_stress", "vix_inverted"}
    assert result.stress == "high"  # four flags
    elevated = calm_series() | {"NFCI": daily([0.3]), "STLFSI4": daily([1.5])}
    assert assess(RULES, T, elevated, spy, []).stress == "elevated"
    crisis = calm_series() | {
        "BAMLH0A0HYM2": daily([9.0]),
        "VIXCLS": daily([45]),
        "VXVCLS": daily([35]),
    }
    crash = bars([100.0] * 250 + [70.0])
    result = assess(RULES, T, crisis, crash, [])
    assert (result.stress, result.dimensions[3].state) == ("crisis", "distressed")


def test_nothing_known_is_unavailable_not_normal() -> None:
    result = assess(RULES, T, {}, [], [])
    assert (result.stress, result.flags_available, result.quadrant) == (None, 0, None)
    assert {d.state for d in result.dimensions} == {"unavailable"}


def test_the_rules_file_needs_one_active_version() -> None:
    raw = yaml.safe_load(
        Path(get_settings().resolved_config_dir() / "regime_rules.yaml").read_text()
    )
    raw["rule_sets"][0]["status"] = "retired"
    with pytest.raises(ValueError, match="exactly one rule set must be active"):
        RegimeRulesFile.model_validate(raw)
