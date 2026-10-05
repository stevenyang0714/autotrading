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

# FRED series shown on the Macro page (M0.6): reported values with vintages, one term per
# series in config/macro_series.yaml (a test keeps the two in step).
MACRO_SERIES_TERMS = (
    "macro_cpi",
    "macro_core_pce",
    "macro_unemployment_rate",
    "macro_nonfarm_payrolls",
    "macro_real_gdp",
    "macro_fed_funds",
    "macro_treasury_2y",
    "macro_treasury_10y",
    "macro_curve_10y_2y",
    "macro_hy_oas",
    "macro_vix",
)

# Indicators computed on the overview (M0.6, ADR-016): term id -> function in domain/indicators.
OVERVIEW_INDICATORS = {
    "cpi_inflation_yoy": "yoy_percent",
    "core_pce_inflation_yoy": "yoy_percent",
    "payrolls_monthly_change": "latest_change",
    "payrolls_prior_month_revision": "revision",
    "sahm_rule_indicator": "sahm_indicator",
    "real_gdp_growth_annualized": "annualized_growth",
    "real_fed_funds_rate": "yoy_percent",
    "yield_curve_inversion": "inversion_streak",
    "hy_oas_percentile": "percentile_rank",
    "vix_percentile_1y": "percentile_rank",
}

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
    *(
        MetricDefinition(
            term_id=term_id,
            methodology_version="0.1.0",
            computed_by="autotrading.adapters.fred.series.FredSeriesJob",
        )
        for term_id in MACRO_SERIES_TERMS
    ),
    *(
        MetricDefinition(
            term_id=term_id,
            methodology_version="0.1.0",
            computed_by=f"autotrading.domain.indicators.{function}",
        )
        for term_id, function in OVERVIEW_INDICATORS.items()
    ),
)
