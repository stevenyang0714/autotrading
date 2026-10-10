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
    # M1.1 (ADR-021)
    "shares_outstanding",
    "shares_outstanding_cover",
    "shares_repurchased",
    "repurchase_authorized",
    "repurchase_remaining",
    "depreciation_amortization",
    "stockholders_equity",
    "dividends_paid",
    "interest_expense",
    "income_tax_expense",
    "pretax_income",
    # M1.4b (ADR-025 B11)
    "eps_basic",
    "basic_shares",
)

# Metrics whose definition changed since 0.1.0 (ADR-025): repurchase_authorized only corroborates
# the 8-K announcements since M1.4a; diluted_shares_change falls back to basic shares where
# nothing dilutes (B11).
METHODOLOGY = {"repurchase_authorized": "0.2.0", "diluted_shares_change": "0.2.0"}

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
            methodology_version=METHODOLOGY.get(metric_id, "0.1.0"),
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
    # M1.1 (ADR-021): computed at read time from facts known at the As known on time.
    *(
        MetricDefinition(
            term_id=term_id,
            methodology_version=METHODOLOGY.get(term_id, "0.1.0"),
            computed_by=f"autotrading.domain.{function}",
        )
        for term_id, function in {
            "free_cash_flow": "derived.free_cash_flow",
            "total_debt": "derived.total_debt",
            "net_debt": "derived.net_debt",
            "quarterly_derived_value": "quarters.quarters",
            "trailing_twelve_months": "quarters.trailing_twelve_months",
            "split_adjusted": "splits.adjust",
            # M1.2 (ADR-022)
            "valuation_price": "valuation.select_price",
            "market_cap": "valuation.valuation",
            "enterprise_value": "valuation.valuation",
            "eps_diluted_ttm": "valuation.ttm_eps",
            "ebitda_ttm": "valuation.valuation",
            "pe_ratio_ttm": "valuation.valuation",
            "ev_to_ebitda": "valuation.valuation",
            "ev_to_sales": "valuation.valuation",
            "price_to_book": "valuation.valuation",
            "fcf_yield": "valuation.valuation",
            "earnings_yield": "valuation.valuation",
            # M1.3a (ADR-023): model output, from facts known at T and an assumption version.
            "fair_value_dcf": "fair_value.fair_value",
            "owner_fcf": "fair_value.owner_fcf",
            "discount_rate": "fair_value.fair_value",
            "scenario_range": "fair_value.fair_value",
            "implied_upside": "fair_value.fair_value",
            "margin_of_safety": "fair_value.fair_value",
            "reverse_dcf_growth": "fair_value.reverse_growth",
            "multiple_percentile": "fair_value.relative",
            # M1.3b (ADR-024): the Research Record, from facts known at T.
            **{
                term_id: "research.research_record"
                for term_id in (
                    "revenue_growth",
                    "gross_margin",
                    "operating_margin",
                    "net_margin",
                    "effective_tax_rate",
                    "nopat",
                    "invested_capital",
                    "roic",
                    "roe",
                    "fcf_conversion",
                    "net_debt_to_ebitda",
                    "cash_returned",
                    "cash_returned_to_fcf",
                    "diluted_shares_change",
                )
            },
            # M1.4a (ADR-025): buybacks, from facts, closes and 8-K statements known at T.
            **{
                term_id: "buyback.buyback_record"
                for term_id in (
                    "buyback_intensity",
                    "repurchase_to_fcf",
                    "sbc_offset",
                    "debt_funded_buyback",
                    "net_share_reduction",
                    "net_share_reduction_pct",
                )
            },
            "repurchase_announcement": "buyback_announcements.statement",
        }.items()
    ),
    MetricDefinition(
        term_id="price_change_1d",
        methodology_version="0.1.0",
        computed_by="autotrading.domain.prices.change_percent",
    ),
    MetricDefinition(
        term_id="pct_below_52w_high",
        methodology_version="0.1.0",
        computed_by="autotrading.domain.prices.below_high_percent",
    ),
)
