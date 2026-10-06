"""Instrument page fundamentals (M0.5b): which stored facts form the annual and balance-sheet
tables, and which issuer an instrument had at a point in time (ADR-014).

Pure functions over already point-in-time-filtered facts (`as_of`, ADR-012); no I/O.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

# Table rows, in display order. Duration metrics go into the annual table, instants dated at the
# balance sheet into the balance sheet, and instants with their own date (the cover page, a
# board authorization) are shown as the latest value with that date (adapters/sec/concepts.py
# defines the period type of each).
ANNUAL_METRICS: tuple[str, ...] = (
    "revenue",
    "gross_profit",
    "operating_income",
    "pretax_income",
    "income_tax_expense",
    "net_income",
    "eps_diluted",
    "diluted_shares",
    "interest_expense",
    "depreciation_amortization",
    "operating_cash_flow",
    "capex",
    "share_repurchases",
    "shares_repurchased",
    "dividends_paid",
    "stock_based_compensation",
)
BALANCE_SHEET_METRICS: tuple[str, ...] = (
    "cash",
    "long_term_debt_current",
    "long_term_debt_noncurrent",
    "commercial_paper",
    "stockholders_equity",
    "shares_outstanding",
    "repurchase_remaining",
)
LATEST_METRICS: tuple[str, ...] = (
    "shares_outstanding_cover",
    "repurchase_authorized",
)

# A fiscal year: 52/53-week years last 364 or 371 days; calendar years 365/366.
FISCAL_YEAR_DAYS = range(350, 381)
ANNUAL_COLUMNS = 3
BALANCE_SHEET_COLUMNS = 3


class PeriodFact(Protocol):
    @property
    def entity_id(self) -> UUID: ...
    @property
    def metric_id(self) -> str: ...
    @property
    def unit(self) -> str: ...
    @property
    def period_start(self) -> date | None: ...
    @property
    def period_end(self) -> date: ...


@dataclass(frozen=True, order=True)
class Period:
    end: date
    start: date | None = None  # None for balance-sheet instants


def merge_by_precedence[FactT: PeriodFact](
    facts: Iterable[FactT], precedence: Sequence[UUID]
) -> list[FactT]:
    """One fact per (metric, unit, period): the one from the entity earliest in `precedence`
    (the current issuer first, then its predecessors). Facts of other entities are dropped."""
    rank = {entity_id: i for i, entity_id in enumerate(precedence)}
    best: dict[tuple[str, str, date | None, date], FactT] = {}
    for fact in facts:
        if fact.entity_id not in rank:
            continue
        key = (fact.metric_id, fact.unit, fact.period_start, fact.period_end)
        current = best.get(key)
        if current is None or rank[fact.entity_id] < rank[current.entity_id]:
            best[key] = fact
    return list(best.values())


def is_fiscal_year(fact: PeriodFact) -> bool:
    return fact.period_start is not None and (
        (fact.period_end - fact.period_start).days in FISCAL_YEAR_DAYS
    )


def annual_periods(facts: Iterable[PeriodFact], count: int = ANNUAL_COLUMNS) -> list[Period]:
    """The latest `count` fiscal years, newest first. If two year-long periods end on the same
    day (e.g. a restated start date), the one more metrics use wins."""
    starts: dict[date, Counter[date]] = defaultdict(Counter)
    for fact in facts:
        if fact.metric_id in ANNUAL_METRICS and is_fiscal_year(fact) and fact.period_start:
            starts[fact.period_end][fact.period_start] += 1
    ends = sorted(starts, reverse=True)[:count]
    return [Period(end=end, start=starts[end].most_common(1)[0][0]) for end in ends]


def balance_sheet_periods(
    facts: Iterable[PeriodFact],
    fiscal_years: Sequence[Period],
    count: int = BALANCE_SHEET_COLUMNS,
) -> list[Period]:
    """The latest balance-sheet date, then fiscal year ends, newest first, `count` at most."""
    instants = {
        fact.period_end
        for fact in facts
        if fact.metric_id in BALANCE_SHEET_METRICS and fact.period_start is None
    }
    if not instants:
        return []
    wanted = [max(instants)]
    for year in fiscal_years:
        if year.end in instants and year.end not in wanted:
            wanted.append(year.end)
    return [Period(end=end) for end in sorted(wanted, reverse=True)[:count]]


@dataclass(frozen=True)
class Succession:
    predecessor_entity_id: UUID
    successor_entity_id: UUID
    effective_at: datetime


def issuer_at(current: UUID, successions: Iterable[Succession], known_at: datetime) -> UUID:
    """Walk back from the current issuer while `known_at` is before the succession."""
    by_successor = {s.successor_entity_id: s for s in successions}
    issuer = current
    seen = {issuer}
    while (step := by_successor.get(issuer)) is not None and known_at < step.effective_at:
        issuer = step.predecessor_entity_id
        if issuer in seen:  # a cycle in curated data: stop rather than loop
            break
        seen.add(issuer)
    return issuer


def entity_precedence(current: UUID, successions: Iterable[Succession]) -> list[UUID]:
    """Current issuer first, then predecessors, nearest first."""
    by_successor = {s.successor_entity_id: s for s in successions}
    order = [current]
    while (step := by_successor.get(order[-1])) is not None:
        if step.predecessor_entity_id in order:
            break
        order.append(step.predecessor_entity_id)
    return order
