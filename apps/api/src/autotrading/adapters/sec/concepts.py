"""Internal metric_id -> XBRL concepts, in priority order (ADR-013, ADR-021).

Companies tag the same line item with different concepts over time (revenue moved to
RevenueFromContractWithCustomerExcludingAssessedTax with ASC 606 in 2018; buyback
authorizations moved from us-gaap to srt) or by preference. For each filing and period the
highest-priority concept that filing reports wins; the chosen concept is stored with the value
(financial_facts.source_concept).

Concepts are qualified by taxonomy: us-gaap, dei (cover page) or srt. Only concepts with the
same meaning are listed. Where a company reports none of them (a bank has no gross profit),
the metric stays unavailable instead of being approximated. Total debt, net debt and free cash
flow are derived from stored components at read time (domain/derived.py, ADR-021).
"""

from dataclasses import dataclass
from typing import Literal

TAXONOMIES = ("us-gaap", "dei", "srt")

PeriodKind = Literal["duration", "instant"]


def split_concept(concept: str) -> tuple[str, str]:
    """`us-gaap:Revenues` -> ("us-gaap", "Revenues")."""
    taxonomy, _, name = concept.partition(":")
    if taxonomy not in TAXONOMIES or not name:
        raise ValueError(f"not a qualified concept of {TAXONOMIES}: {concept}")
    return taxonomy, name


@dataclass(frozen=True)
class MetricMapping:
    metric_id: str
    concepts: tuple[str, ...]  # qualified, priority order
    unit: str  # SEC unit key: USD, shares, USD/shares
    period: PeriodKind

    def __post_init__(self) -> None:
        for concept in self.concepts:
            split_concept(concept)

    @property
    def currency(self) -> str | None:
        return "USD" if self.unit.startswith("USD") else None


def gaap(*names: str) -> tuple[str, ...]:
    return tuple(f"us-gaap:{name}" for name in names)


METRIC_MAPPINGS: tuple[MetricMapping, ...] = (
    MetricMapping(
        "revenue",
        gaap(
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
            "RevenuesNetOfInterestExpense",
        ),
        "USD",
        "duration",
    ),
    MetricMapping("gross_profit", gaap("GrossProfit"), "USD", "duration"),
    MetricMapping("operating_income", gaap("OperatingIncomeLoss"), "USD", "duration"),
    MetricMapping("net_income", gaap("NetIncomeLoss"), "USD", "duration"),
    MetricMapping("eps_diluted", gaap("EarningsPerShareDiluted"), "USD/shares", "duration"),
    MetricMapping(
        "diluted_shares",
        gaap("WeightedAverageNumberOfDilutedSharesOutstanding"),
        "shares",
        "duration",
    ),
    MetricMapping("cash", gaap("CashAndCashEquivalentsAtCarryingValue"), "USD", "instant"),
    MetricMapping(
        "long_term_debt_noncurrent",
        gaap("LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"),
        "USD",
        "instant",
    ),
    MetricMapping(
        "long_term_debt_current",
        gaap("LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"),
        "USD",
        "instant",
    ),
    MetricMapping("commercial_paper", gaap("CommercialPaper"), "USD", "instant"),
    MetricMapping(
        "operating_cash_flow", gaap("NetCashProvidedByUsedInOperatingActivities"), "USD", "duration"
    ),
    MetricMapping(
        "capex",
        gaap("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"),
        "USD",
        "duration",
    ),
    MetricMapping(
        "share_repurchases", gaap("PaymentsForRepurchaseOfCommonStock"), "USD", "duration"
    ),
    MetricMapping(
        "stock_based_compensation",
        gaap("ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"),
        "USD",
        "duration",
    ),
    # M1.1 (ADR-021). Checked against the ten issuers' filings on 2026-10-06.
    MetricMapping("shares_outstanding", gaap("CommonStockSharesOutstanding"), "shares", "instant"),
    MetricMapping(
        "shares_outstanding_cover", ("dei:EntityCommonStockSharesOutstanding",), "shares", "instant"
    ),
    MetricMapping(
        "shares_repurchased",
        gaap(
            "StockRepurchasedAndRetiredDuringPeriodShares",
            "StockRepurchasedDuringPeriodShares",
            "TreasuryStockSharesAcquired",
        ),
        "shares",
        "duration",
    ),
    MetricMapping(
        "repurchase_authorized",
        (
            "srt:StockRepurchaseProgramAuthorizedAmount1",
            "us-gaap:StockRepurchaseProgramAuthorizedAmount1",
            "us-gaap:StockRepurchaseProgramAuthorizedAmount",
        ),
        "USD",
        "instant",
    ),
    MetricMapping(
        "repurchase_remaining",
        gaap(
            "StockRepurchaseProgramRemainingAuthorizedRepurchaseAmount1",
            "StockRepurchaseProgramRemainingAuthorizedRepurchaseAmount",
        ),
        "USD",
        "instant",
    ),
    MetricMapping(
        "depreciation_amortization",
        gaap(
            "DepreciationDepletionAndAmortization",
            "DepreciationAndAmortization",
            "DepreciationAmortizationAndAccretionNet",
        ),
        "USD",
        "duration",
    ),
    MetricMapping("stockholders_equity", gaap("StockholdersEquity"), "USD", "instant"),
    MetricMapping(
        "dividends_paid",
        gaap("PaymentsOfDividendsCommonStock", "PaymentsOfDividends"),
        "USD",
        "duration",
    ),
    MetricMapping(
        "interest_expense",
        gaap("InterestExpenseNonoperating", "InterestExpense", "InterestExpenseDebt"),
        "USD",
        "duration",
    ),
    MetricMapping("income_tax_expense", gaap("IncomeTaxExpenseBenefit"), "USD", "duration"),
    MetricMapping(
        "pretax_income",
        gaap(
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        ),
        "USD",
        "duration",
    ),
    # M1.4b (ADR-025 B11): basic values, used for diluted shares only where a company reports
    # diluted EPS equal to basic EPS and tags no diluted share count (ExxonMobil since 2014).
    MetricMapping("eps_basic", gaap("EarningsPerShareBasic"), "USD/shares", "duration"),
    MetricMapping(
        "basic_shares",
        gaap("WeightedAverageNumberOfSharesOutstandingBasic"),
        "shares",
        "duration",
    ),
)

MAPPINGS_BY_METRIC = {mapping.metric_id: mapping for mapping in METRIC_MAPPINGS}
MAPPED_CONCEPTS = frozenset(concept for m in METRIC_MAPPINGS for concept in m.concepts)
