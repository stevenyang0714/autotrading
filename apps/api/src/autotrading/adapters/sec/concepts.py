"""Internal metric_id -> us-gaap XBRL concepts, in priority order (ADR-013).

Companies tag the same line item with different concepts over time (revenue moved to
RevenueFromContractWithCustomerExcludingAssessedTax with ASC 606 in 2018) or by preference.
For each filing and period the highest-priority concept that filing reports wins; the chosen
concept is stored with the value (financial_facts.source_concept).

Only concepts with the same meaning are listed. Where a company reports none of them (a bank
has no gross profit), the metric stays unavailable instead of being approximated. "Total
debt" is not a metric here: its components are stored and Phase 1 derives it (ADR-013).
"""

from dataclasses import dataclass
from typing import Literal

TAXONOMY = "us-gaap"

PeriodKind = Literal["duration", "instant"]


@dataclass(frozen=True)
class MetricMapping:
    metric_id: str
    concepts: tuple[str, ...]  # priority order
    unit: str  # SEC unit key: USD, shares, USD/shares
    period: PeriodKind

    @property
    def currency(self) -> str | None:
        return "USD" if self.unit.startswith("USD") else None


METRIC_MAPPINGS: tuple[MetricMapping, ...] = (
    MetricMapping(
        "revenue",
        (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
            "RevenuesNetOfInterestExpense",
        ),
        "USD",
        "duration",
    ),
    MetricMapping("gross_profit", ("GrossProfit",), "USD", "duration"),
    MetricMapping("operating_income", ("OperatingIncomeLoss",), "USD", "duration"),
    MetricMapping("net_income", ("NetIncomeLoss",), "USD", "duration"),
    MetricMapping("eps_diluted", ("EarningsPerShareDiluted",), "USD/shares", "duration"),
    MetricMapping(
        "diluted_shares", ("WeightedAverageNumberOfDilutedSharesOutstanding",), "shares", "duration"
    ),
    MetricMapping("cash", ("CashAndCashEquivalentsAtCarryingValue",), "USD", "instant"),
    MetricMapping(
        "long_term_debt_noncurrent",
        ("LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"),
        "USD",
        "instant",
    ),
    MetricMapping(
        "long_term_debt_current",
        ("LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"),
        "USD",
        "instant",
    ),
    MetricMapping("commercial_paper", ("CommercialPaper",), "USD", "instant"),
    MetricMapping(
        "operating_cash_flow", ("NetCashProvidedByUsedInOperatingActivities",), "USD", "duration"
    ),
    MetricMapping(
        "capex",
        ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"),
        "USD",
        "duration",
    ),
    MetricMapping("share_repurchases", ("PaymentsForRepurchaseOfCommonStock",), "USD", "duration"),
    MetricMapping(
        "stock_based_compensation",
        ("ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"),
        "USD",
        "duration",
    ),
)

MAPPINGS_BY_METRIC = {mapping.metric_id: mapping for mapping in METRIC_MAPPINGS}
MAPPED_CONCEPTS = frozenset(concept for m in METRIC_MAPPINGS for concept in m.concepts)


def qualified(concept: str) -> str:
    return f"{TAXONOMY}:{concept}"
