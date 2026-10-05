from autotrading.domain.registries import (
    DEFAULT_MODE_LABELS,
    SIGNAL_FAMILIES,
    SOURCE_TIERS,
    STRATEGIES,
)


def test_ten_signal_families_numbered_one_to_ten() -> None:
    assert [family.id for family in SIGNAL_FAMILIES] == list(range(1, 11))
    assert len({family.name for family in SIGNAL_FAMILIES}) == 10


def test_twelve_strategies_s1_to_s12() -> None:
    assert [strategy.id for strategy in STRATEGIES] == [f"S{n}" for n in range(1, 13)]
    assert len({strategy.name for strategy in STRATEGIES}) == 12


def test_x_researcher_is_a_source_stream_not_a_strategy() -> None:
    # 02 §18 registry rule: X Researcher is not S10.
    assert all("X " not in strategy.name for strategy in STRATEGIES)


def test_only_s1_to_s4_default_to_paper_semi_auto() -> None:
    paper = [s.id for s in STRATEGIES if s.default_mode == "paper_semi_auto"]
    assert paper == ["S1", "S2", "S3", "S4"]
    assert all(s.default_mode in DEFAULT_MODE_LABELS for s in STRATEGIES)


def test_source_tier_one_is_strongest() -> None:
    # Errata E2: lower number = stronger evidence.
    assert [tier.tier for tier in SOURCE_TIERS] == [1, 2, 3, 4]
    assert SOURCE_TIERS[0].role == "trade-critical confirmation"
    assert "never sole execution evidence" in SOURCE_TIERS[3].role
