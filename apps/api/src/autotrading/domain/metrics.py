"""Backend metric registry (M0.4 validation rule 3).

Every metric the backend computes and the UI may show is declared here with its glossary
term and methodology version. A test fails when a version drifts from the glossary entry, so
a change to a calculation forces a matching change to its tooltip text.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricDefinition:
    term_id: str
    methodology_version: str
    computed_by: str


# Reported XBRL values (M0.5): "computed" means selected per adapters/sec/concepts.py.
SEC_XBRL_METRICS = (
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "eps_diluted",
    "diluted_shares",
    "cash",
    "long_term_debt_noncurrent",
    "long_term_debt_current",
    "commercial_paper",
    "operating_cash_flow",
    "capex",
    "share_repurchases",
    "stock_based_compensation",
)

METRICS: tuple[MetricDefinition, ...] = (
    MetricDefinition(
        term_id="data_freshness",
        methodology_version="0.1.0",
        computed_by="autotrading.domain.freshness.freshness_status",
    ),
    *(
        MetricDefinition(
            term_id=metric_id,
            methodology_version="0.1.0",
            computed_by="autotrading.adapters.sec.concepts.METRIC_MAPPINGS",
        )
        for metric_id in SEC_XBRL_METRICS
    ),
)
