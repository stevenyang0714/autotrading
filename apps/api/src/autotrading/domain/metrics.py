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
METHODOLOGY = {
    "repurchase_authorized": "0.2.0",
    "diluted_shares_change": "0.2.0",
    # B12-B14 (buyback rule 0.2.0): a period end's market cap on the latest dated share count;
    # mega caps pass ACTIVE's quarter test on any repurchase and score intensity 100 at 2%.
    "buyback_intensity": "0.2.0",
    "quarter_repurchase_to_market_cap": "0.2.0",
    "buyback_state_active": "0.2.0",
    "buyback_score_intensity": "0.2.0",
    # M2.3 (ADR-031): TRADE-READY and L4 read the standard risk check; the check is defined.
    "buyback_state_trade_ready": "0.2.0",
    "convergence_l4": "0.2.0",
    "risk_check": "0.2.0",
    # M2.4 (ADR-032): signals come from the S3 rotation too.
    "signal": "0.2.0",
    # M3.0 (ADR-036): regime rules 0.2.0 change the crisis and high rules, the NFCI flag and the
    # quadrant's reading of inflation.
    "regime_quadrant": "0.2.0",
    "stress_state": "0.2.0",
    "stress_flag_nfci": "0.2.0",
    # M3.0 (ADR-036 D5, D7): daily rotation history; S4 assessed daily with signals.
    "rotation_rebalance": "0.2.0",
    "regime_gate": "0.2.0",
    "defensive_switch": "0.2.0",
    "medium_term_momentum": "0.2.0",
    # M3.0b (ADR-037): alerts may be pushed to Telegram; S4 targets raise alerts.
    "alert": "0.4.0",
    "rotation_alert": "0.2.0",
}

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
    "macro_vix_3m",
    "macro_nfci",
    "macro_nfci_credit",
    "macro_stlfsi",
    "macro_wti_oil",
    "macro_dollar_index",
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
            # M1.4b (ADR-025): states and score under a rule version, from evidence known at T.
            **{
                term_id: "buyback_states.assess"
                for term_id in (
                    "buyback_state",
                    "buyback_state_watch",
                    "buyback_state_active",
                    "buyback_state_high_conviction",
                    "buyback_state_trade_ready",
                    "remaining_to_market_cap",
                    "quarter_repurchase_to_market_cap",
                    "fcf_funding",
                    "net_debt_change_yoy",
                    "fcf_yield_to_median",
                    "close_vs_moving_average",
                    "relative_return_1m",
                    "market_confirmation",
                    "buyback_quality_score",
                    "buyback_score_undervaluation",
                    "buyback_score_intensity",
                    "buyback_score_fcf_quality",
                    "buyback_score_balance_sheet",
                    "buyback_score_discipline",
                    "buyback_score_share_count",
                    "net_debt_to_fcf",
                    "disciplined_years",
                    "mega_cap",
                )
            },
            # M1.5 (ADR-026): earnings events, from 8-Ks, the matched report and closes.
            "earnings_timing": "earnings.timing",
            "earnings_report": "earnings.match_report",
            "earnings_actuals": "earnings.actuals",
            "change_qoq": "earnings.actuals",
            "change_yoy": "earnings.actuals",
            "earnings_reaction": "earnings.reaction",
            "earnings_volume_ratio": "earnings.reaction",
            "guidance_statement": "guidance.guidance",
            # M1.6 (ADR-027): signals from buyback states; paper returns and replay.
            "signal": "signals.buyback_signal",
            "execution_eligibility": "signals.buyback_signal",
            "paper_return": "journal.paper_return",
            "journal_replay": "journal.compare",
            # M1.7 (ADR-028): convergence levels from buyback readings and Phase 1 events.
            **{
                term_id: "convergence.assess"
                for term_id in (
                    "convergence_level",
                    "convergence_l0",
                    "convergence_l1",
                    "convergence_l2",
                    "convergence_l3",
                    "convergence_l4",
                    "independent_evidence",
                    "valuation_support",
                )
            },
            # M2.1 (ADR-029): the macro regime and stress state.
            **{
                term_id: "regime.assess"
                for term_id in (
                    "regime",
                    "regime_growth",
                    "regime_inflation",
                    "regime_policy",
                    "regime_credit",
                    "regime_volatility",
                    "regime_quadrant",
                    "stress_state",
                    "stress_flag_credit",
                    "stress_flag_volatility",
                    "stress_flag_nfci",
                    "stress_flag_stlfsi",
                    "stress_flag_vix_term",
                    "stress_flag_drawdown",
                    "stress_flag_dollar",
                    "stress_flag_oil",
                    "stress_flag_stock_bond",
                )
            },
            # M2.2 (ADR-030): price, trend and factor measures.
            **{
                term_id: "factors.price_measures"
                for term_id in (
                    "momentum_12_1",
                    "momentum_6_1",
                    "reversal_1m",
                    "close_vs_sma_50",
                    "close_vs_sma_200",
                    "volatility_60d",
                    "beta_252d",
                    "relative_momentum_12_1",
                    "relative_momentum_6_1",
                    "total_return",
                    "dividend_gap",
                )
            },
            "factor_percentile": "fair_value.relative",
            "factor_snapshot": "factors.record_snapshot",
            # M2.3 (ADR-031): the paper portfolio and risk checks.
            **{
                term_id: "risk.check"
                for term_id in (
                    "risk_check",
                    "risk_veto",
                    "risk_limit_position",
                    "risk_limit_max_loss",
                    "risk_limit_sector",
                    "risk_limit_volume",
                    "risk_limit_gross",
                    "risk_limit_price",
                    "standard_position_check",
                    "max_loss",
                )
            },
            **{
                term_id: "risk.portfolio"
                for term_id in (
                    "paper_portfolio",
                    "portfolio_snapshot",
                    "position_weight",
                    "gross_exposure",
                    "net_exposure",
                    "beta_exposure",
                    "portfolio_drawdown",
                    "portfolio_equity",
                    "average_daily_volume",
                    "days_to_exit",
                )
            },
            # M2.4 (ADR-032): the S3 ETF rotation and the Opportunity Radar candidates.
            **{
                term_id: "rotation.assess"
                for term_id in (
                    "etf_rotation",
                    "rotation_target",
                    "trend_filter",
                    "regime_gate",
                    "risk_sleeve",
                    "defensive_sleeve",
                    "high_beta",
                    "rotation_rebalance",
                    "defensive_switch",
                )
            },
            "rotation_alert": "rotation.rotation_alert",
            # M2.5 (ADR-033): backtests without performance, and S4.
            **{
                term_id: "backtest.run"
                for term_id in (
                    "backtest",
                    "walk_forward",
                    "in_sample",
                    "out_of_sample",
                    "cost_model",
                    "half_spread",
                    "slippage",
                    "turnover",
                    "holding_period",
                    "cost_drag",
                    "performance_withheld",
                    "next_close_fill",
                    "risk_overlay",
                )
            },
            "medium_term_momentum": "momentum.assess",
            "momentum_target": "momentum.daily",  # M3.0 (ADR-036 D7)
            "momentum_alert": "momentum.momentum_alert",  # M3.0b (ADR-037)
            "alert_delivery": "delivery.message",
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
