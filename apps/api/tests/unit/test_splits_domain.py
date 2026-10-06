"""Split adjustment of per-share history (ADR-021)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from fractions import Fraction

from autotrading.adapters.alpaca.splits import load_curated
from autotrading.domain.splits import (
    ReportedVersion,
    Split,
    adjust,
    effective_at,
    unexplained_splits,
)
from autotrading.settings import get_settings

AAPL_2014 = Split(date(2014, 6, 9), Decimal(1), Decimal(7))
AAPL_2020 = Split(date(2020, 8, 31), Decimal(1), Decimal(4))
SPLITS = [AAPL_2014, AAPL_2020]
FY2019_10K = datetime(2019, 10, 31, 20, 3, tzinfo=UTC)  # accession 0000320193-19-000119
FY2020_10K = datetime(2020, 10, 30, 20, 2, tzinfo=UTC)  # accession 0000320193-20-000096
TODAY = datetime(2026, 10, 6, tzinfo=UTC)


def test_a_split_is_effective_from_the_start_of_its_ex_date_in_new_york() -> None:
    assert effective_at(date(2020, 8, 31)) == datetime(2020, 8, 31, 4, 0, tzinfo=UTC)  # EDT
    assert effective_at(date(2014, 1, 6)) == datetime(2014, 1, 6, 5, 0, tzinfo=UTC)  # EST


def test_eps_reported_before_a_split_is_divided_by_its_ratio() -> None:
    # Apple FY2017 diluted EPS, last reported in the FY2019 10-K (before the 2020 4-for-1).
    adjusted = adjust("eps_diluted", Decimal("9.21"), FY2019_10K, TODAY, SPLITS)
    assert adjusted is not None
    assert (adjusted.value, adjusted.factor, adjusted.splits) == (
        Decimal("2.3025"),
        Fraction(4),
        (AAPL_2020,),
    )


def test_share_counts_are_multiplied_and_older_values_take_every_later_split() -> None:
    reported_2013 = datetime(2013, 10, 30, 20, tzinfo=UTC)
    adjusted = adjust("diluted_shares", Decimal(931662000), reported_2013, TODAY, SPLITS)
    assert adjusted is not None
    assert (adjusted.value, adjusted.factor) == (Decimal(26086536000), Fraction(28))


def test_no_adjustment_before_the_split_or_after_the_restatement() -> None:
    before_split = datetime(2020, 8, 30, tzinfo=UTC)
    assert adjust("eps_diluted", Decimal("9.21"), FY2019_10K, before_split, SPLITS) is None
    # The FY2020 10-K already reports FY2019 EPS on the new basis (2.97).
    assert adjust("eps_diluted", Decimal("2.97"), FY2020_10K, TODAY, SPLITS) is None
    assert adjust("revenue", Decimal(1), FY2019_10K, TODAY, SPLITS) is None


def version(
    value: str, reported_at: datetime, accession: str, metric: str = "eps_diluted"
) -> ReportedVersion:
    return ReportedVersion(
        metric, date(2018, 9, 30), date(2019, 9, 28), Decimal(value), reported_at, accession
    )


SPLIT_RESTATEMENT = [
    version("11.89", FY2019_10K, "0000320193-19-000119"),
    version("2.97", FY2020_10K, "0000320193-20-000096"),
    version("4648913000", FY2019_10K, "0000320193-19-000119", "diluted_shares"),
    version("18595651000", FY2020_10K, "0000320193-20-000096", "diluted_shares"),
]


def test_a_restatement_explained_by_a_recorded_split_is_not_flagged() -> None:
    assert unexplained_splits(SPLIT_RESTATEMENT, SPLITS) == []


def test_eps_and_shares_restated_like_a_split_without_a_recorded_split_are_flagged() -> None:
    [finding] = unexplained_splits(SPLIT_RESTATEMENT, [AAPL_2014])
    assert "ratio of about 4" in finding and "0000320193-20-000096" in finding


def test_an_eps_restatement_alone_is_not_a_split() -> None:
    # Apple Q3 FY2009 EPS 1.35 -> 2.01 (revenue recognition change, 2010): about 2/3, but
    # the share count did not move.
    versions = [
        version("1.35", FY2019_10K, "0001193125-09-153165"),
        version("2.01", FY2020_10K, "0001193125-10-162840"),
        version("909000000", FY2019_10K, "0001193125-09-153165", "diluted_shares"),
        version("909000000", FY2020_10K, "0001193125-10-162840", "diluted_shares"),
    ]
    assert unexplained_splits(versions, []) == []
    assert unexplained_splits(versions[:2], []) == []


def test_reviewed_split_list_is_valid_and_cites_8ks() -> None:
    curated = load_curated(get_settings().resolved_config_dir())
    assert {(s.ticker, s.ex_date, s.new_rate / s.old_rate) for s in curated} == {
        ("AAPL", date(2014, 6, 9), 7),
        ("GOOGL", date(2014, 4, 3), 2),
    }
    assert all(s.source_url.endswith("-index.htm") for s in curated)
