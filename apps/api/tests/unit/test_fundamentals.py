"""domain/fundamentals: issuer precedence, fiscal-year columns and the issuer at a time."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from autotrading.adapters.sec.concepts import METRIC_MAPPINGS
from autotrading.domain.fundamentals import (
    ANNUAL_METRICS,
    BALANCE_SHEET_METRICS,
    LATEST_METRICS,
    Period,
    Succession,
    annual_periods,
    balance_sheet_periods,
    entity_precedence,
    issuer_at,
    merge_by_precedence,
)

HOLDINGS, EXXON, OLDER = uuid4(), uuid4(), uuid4()
REORGANIZED = datetime(2026, 7, 1, 16, 36, 49, tzinfo=UTC)
SUCCESSIONS = [Succession(EXXON, HOLDINGS, REORGANIZED)]


@dataclass(frozen=True)
class Fact:
    entity_id: UUID
    metric_id: str
    period_end: date
    period_start: date | None = None
    unit: str = "USD"


def year(entity: UUID, metric: str, end: date, days: int = 365) -> Fact:
    return Fact(entity, metric, end, date.fromordinal(end.toordinal() - days + 1))


def test_table_metrics_match_the_concept_period_types() -> None:
    kinds = {m.metric_id: m.period for m in METRIC_MAPPINGS}
    assert {kinds[m] for m in ANNUAL_METRICS} == {"duration"}
    assert {kinds[m] for m in BALANCE_SHEET_METRICS} == {"instant"}
    assert {kinds[m] for m in LATEST_METRICS} == {"instant"}
    groups = [ANNUAL_METRICS, BALANCE_SHEET_METRICS, LATEST_METRICS]
    assert sum(len(g) for g in groups) == len(kinds)
    assert set().union(*groups) == set(kinds)


def test_current_issuer_wins_where_both_reported_a_period() -> None:
    mine = year(HOLDINGS, "revenue", date(2025, 12, 31))
    theirs = year(EXXON, "revenue", date(2025, 12, 31))
    older_only = year(EXXON, "revenue", date(2024, 12, 31))
    stranger = year(uuid4(), "revenue", date(2023, 12, 31))
    merged = merge_by_precedence([theirs, mine, older_only, stranger], [HOLDINGS, EXXON])
    assert sorted(merged, key=lambda f: f.period_end) == [older_only, mine]


def test_fiscal_years_are_the_latest_year_long_periods() -> None:
    facts = [
        year(HOLDINGS, "revenue", date(2025, 9, 27), days=364),  # 52-week year
        year(HOLDINGS, "revenue", date(2024, 9, 28), days=371),  # 53-week year
        year(HOLDINGS, "net_income", date(2023, 9, 30)),
        year(HOLDINGS, "net_income", date(2022, 9, 24)),
        year(HOLDINGS, "revenue", date(2026, 6, 27), days=91),  # a quarter: not a year
        year(HOLDINGS, "cash", date(2026, 6, 27), days=365),  # not an annual metric
    ]
    assert [p.end for p in annual_periods(facts)] == [
        date(2025, 9, 27),
        date(2024, 9, 28),
        date(2023, 9, 30),
    ]


def test_balance_sheet_takes_the_latest_date_then_fiscal_year_ends() -> None:
    def cash(end: date) -> Fact:
        return Fact(HOLDINGS, "cash", end)

    facts = [cash(date(2026, 6, 27)), cash(date(2026, 3, 28)), cash(date(2025, 9, 27))]
    facts.append(cash(date(2024, 9, 28)))
    years = [Period(date(2025, 9, 27), date(2024, 9, 29)), Period(date(2024, 9, 28))]
    assert balance_sheet_periods(facts, years) == [
        Period(date(2026, 6, 27)),
        Period(date(2025, 9, 27)),
        Period(date(2024, 9, 28)),
    ]
    assert balance_sheet_periods([], years) == []


def test_issuer_before_a_reorganization_is_the_predecessor() -> None:
    assert issuer_at(HOLDINGS, SUCCESSIONS, datetime(2026, 6, 1, tzinfo=UTC)) == EXXON
    assert issuer_at(HOLDINGS, SUCCESSIONS, REORGANIZED) == HOLDINGS
    chain = [*SUCCESSIONS, Succession(OLDER, EXXON, datetime(1999, 11, 30, tzinfo=UTC))]
    assert issuer_at(HOLDINGS, chain, datetime(1990, 1, 1, tzinfo=UTC)) == OLDER
    assert entity_precedence(HOLDINGS, chain) == [HOLDINGS, EXXON, OLDER]


def test_a_cycle_in_curated_links_does_not_loop() -> None:
    cycle = [*SUCCESSIONS, Succession(HOLDINGS, EXXON, datetime(2000, 1, 1, tzinfo=UTC))]
    assert entity_precedence(HOLDINGS, cycle) == [HOLDINGS, EXXON]
    assert issuer_at(HOLDINGS, cycle, datetime(1990, 1, 1, tzinfo=UTC)) in {HOLDINGS, EXXON}
