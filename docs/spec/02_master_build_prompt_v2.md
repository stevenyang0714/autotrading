MASTER BUILD PROMPT v2.0：AI Global Market Intelligence & Semi-Automated Trading Platform

*可直接交給 coding agent / product-building agent；以 production-oriented skeleton 為目標*

**Version 2.0 | Research / build snapshot: 2026-10-04**

# 使用方式

把本文件視為 canonical build specification。Coding agent 不得自行重命名 strategy IDs、改變 score direction、替換 market-data provider、把 delayed disclosures 當 current positions，或把未經授權資料當 live data。任何無法取得真實資料的 UI 必須顯示 Data unavailable / Demo data。

| **BUILD PRINCIPLE** 360-degree intelligence, selective execution. Research broadly. Trade narrowly. |
| --- |

# 1. SYSTEM ARCHITECTURE

## 1.1 Data Plane

Market prices/volume; equity fundamentals; SEC/issuer filings; macro; corporate actions; options; positioning/flows; English news/web; X watchlists; U.S. congressional PTR; policy; weather/fire/satellite/shipping/ports/commodity/physical data.

## 1.2 Intelligence Plane

Event extraction; entity resolution; topic classification; source provenance; duplicate/repost detection; causal graph; company exposure graph; scenario generation; thesis generation.

## 1.3 Quant Plane

Feature engineering; signal calculations; factor analytics; backtesting; walk-forward; point-in-time handling; portfolio construction; position sizing; stress testing.

## 1.4 Risk Plane

Gross/net; beta; sector/country concentration; factor exposure; currency/commodity exposure; liquidity; drawdown; VaR/Expected Shortfall; tail regime; trade-level invalidation.

## 1.5 Execution Plane

Paper trading; order preview; explicit approval; broker adapter; order routing; fill monitoring; reconciliation; audit trail; kill switch.

Default to paper trading / semi-automated execution. Auto-execution is disabled until strategy eligibility and all risk gates pass.

# 2. SIGNAL FAMILIES

| **#** | **Canonical family** |
| --- | --- |
| 1 | Macro Regime |
| 2 | Corporate Actions & Capital Structure |
| 3 | Fundamental & Valuation |
| 4 | Earnings & Estimates |
| 5 | Price / Trend / Factor |
| 6 | Options & Volatility |
| 7 | Positioning & Flows |
| 8 | Alternative / Physical / Supply Chain |
| 9 | Geopolitical / Policy / Social Intelligence |
| 10 | Tail Risk / Regime Stress |

Do not create separate top-level categories for Trump, X researchers, Congress trades, or English websites. They are source streams/modules within the ten families.

# 3. FUNDAMENTAL RESEARCH ENGINE

Build a persistent company Research Record and continuously update it from point-in-time financial data. The platform is not a generic stock screener.

Income statement: revenue, gross profit/margin, operating income/margin, EBITDA where relevant, net income, EPS.

Balance sheet: cash, total debt, net debt, working capital, PP&E, intangibles.

Cash flow: CFO, capex, FCF, FCF conversion, working-capital effects.

Per-share: diluted shares, SBC, buybacks, equity issuance, option dilution.

Quality: ROIC, ROE, margin stability, FCF quality, balance-sheet strength.

Valuation: DCF, reverse DCF, P/E, EV/EBITDA, EV/Sales, P/B where relevant, FCF yield, earnings yield, SOTP, relative valuation.

Expectations: consensus, revisions, dispersion, guidance, event calendar.

Every valuation output must expose assumptions, scenario range, current price, implied upside/downside, margin of safety, model date, and source as-of date. Fair value is model output, not fact.

# 4. DATA PROVENANCE & POINT-IN-TIME

Every observation: source_id, source_name, source_url, source_tier, published_at, ingested_at, effective_at, timezone, filing_date when relevant, fiscal_period, period_end, as_of_date, restated_flag, confidence, license/access status.

Never overwrite prior data without retaining version history.

Use point-in-time / vintage logic. For macro, support FRED/ALFRED real-time periods and vintages. For SEC, preserve accession-linked filing history and revisions.

Track data freshness and stale-state explicitly. A stale quote or stale source can block execution.

# 5. BUYBACK / CAPITAL ALLOCATION ENGINE

Distinguish authorization, actual repurchase, intensity, remaining authorization, net share reduction, SBC/issuance dilution, FCF funding, debt-funded buyback, historical timing discipline, and valuation context.

Initialize Buyback Quality Score with versioned weights: 30% undervaluation, 20% actual repurchase intensity, 15% FCF quality, 10% balance-sheet strength, 10% historical discipline, 10% net share-count impact, 5% management/insider alignment. These weights are defaults only and must be validated out-of-sample.

BUYBACK WATCH

BUYBACK ACTIVE

BUYBACK HIGH-CONVICTION CANDIDATE

BUYBACK TRADE-READY

Never trigger a buy merely because a company announces a buyback. Require actual-repurchase and/or subsequent share-count evidence plus valuation, quality, and market confirmation.

# 6. PHYSICAL-TO-FINANCIAL CAUSAL ENGINE

Canonical chain: EVENT → PHYSICAL/POLICY CONDITION → SUPPLY/DEMAND → COMMODITY/INPUT PRICE → INDUSTRY ECONOMICS → COMPANY EXPOSURE → REVENUE/COST/MARGIN/EPS/FCF → VALUATION → PRICE CONFIRMATION → TRADE.

Every major graph edge requires evidence and timestamp.

Use company exposure maps and scenario ranges rather than a single deterministic forecast.

For El Niño / Indonesia fire scenarios, test physical evidence before inferring commodity shortage.

The causal engine outputs thesis candidates; Strategy/Risk engines decide execution eligibility.

# 7. TRUMP / WHITE HOUSE / POLICY INTELLIGENCE

Treat political figures as information sources, not investment authorities. Track policy status: statement, proposal, signed action, effective, implementation, challenged/modified, expired/replaced.

Source priority: White House Presidential Actions, official fact sheets, Federal Register where relevant, USTR, Commerce, Treasury, other official agencies.

Each policy object: policy_status, jurisdiction, affected goods/sectors/countries, effective_date, implementation_status, direct/second-order exposure, linked companies/instruments, evidence URLs.

Do not turn political statements into political persuasion.

# 8. ENGLISH-LANGUAGE NEWS & WEB INTELLIGENCE

External market/news sources default to English-first.

Preserve original title, author, publication/update times, URL, language, quoted entities, extracted tickers/commodities/countries/policy entities.

Deduplicate syndication and repost chains.

Prototype with GDELT + official RSS/public English feeds; premium licensed feeds through Source Registry.

A derived summary must always retain the original source link. Unauthorized scraping and paywall-text replication are prohibited as core dependencies.

# 9. X / RESEARCHER WATCHLIST

User-configurable watchlists may include account, list, keyword, ticker, sector, theme. Capture only through permitted/licensed access.

| **Feature** | **Requirement** |
| --- | --- |
| Entity extraction | ticker/company/commodity/country/policy resolution |
| Thesis change | compare current author thesis with prior statements on same entity |
| Evidence quality | measure use of filings/data/first-hand evidence |
| Engagement | attention multiplier only |
| Historical calibration | author thesis versus subsequent outcome; source-specific reliability |
| Execution | X posts alone can never auto-execute |

# 10. U.S. CONGRESS PTR MONITOR

Display Reported Trade, not Current Position. Track trade date, notification date when available, filing date, disclosure lag, asset, ticker, transaction type, owner, amount range, staleness, source URL.

House and Senate PTR disclosures are delayed public disclosures. Never infer intent or current holdings from a single PTR. Amount ranges must be retained exactly as disclosed.

# 11. CORPORATE INSIDER ENGINE

Parse Forms 3/4/5 and transaction codes.

Distinguish open-market purchase/sale, derivative exercise, grant, vesting, tax withholding, gift, 10b5-1 plan and other codes.

Store transaction code, price, shares, post-transaction ownership where available, 10b5-1 flag, filing timestamp.

Never label every insider sale bearish.

# 12. EARNINGS & ESTIMATES ENGINE

Compute fundamental surprise, forward revisions, guidance changes, market confirmation, valuation context, and peer information transfer.

Separate earnings score from Thesis Score / Timing Score / Execution Score.

Use event timestamp and pre-event consensus vintage.

# 13. PRICE / TREND / FACTOR ENGINE

3–12 month momentum; relative strength; breakout; moving-average structure.

Value, size, profitability, investment factor analytics.

Sector/industry relative strength.

Keep thesis quality separate from timing.

# 14. OPTIONS & VOLATILITY ENGINE

Realized vol, implied vol, IV percentile, skew, term structure, expected move, Delta/Gamma/Vega/Theta.

Primary use in MVP: analytics, hedging, defined-risk strategies.

No default auto-trading of illiquid options, wide spreads or 0DTE.

Any options trade must show maximum defined loss where determinable and liquidity checks.

# 15. TAIL RISK / REGIME STRESS ENGINE

Detect fragility, not black swans. Monitor credit spreads, VIX/term structure, funding/liquidity, yield curve, cross-asset correlation, FX stress, commodity shocks, shipping disruption, bank stress.

| **Regime** | **Default behavior** |
| --- | --- |
| NORMAL | normal strategy eligibility |
| ELEVATED | reduce new high-beta exposure |
| HIGH | increase hedge / reduce gross |
| CRISIS | execution-first; stop nonessential new trades |

# 16. SIGNAL CONVERGENCE ENGINE

| **Level** | **Rule** | **System action** |
| --- | --- | --- |
| L0 | single event/signal | record |
| L1 | multiple related signals | watchlist |
| L2 | multiple independent signals + causal chain | thesis |
| L3 | thesis + market confirmation + strategy trigger | trade candidate |
| L4 | L3 + risk + liquidity + sizing + compliance | execution ready |

Independent evidence must be deduplicated. A repost chain is one source, not many.

# 17. INVESTMENT THESIS CARD

Asset; Thesis; Evidence; Catalyst; Valuation; Timing; Risk/Invalidation; Position; Sizing; Scores; Source links; data-as-of.

The system must support explicit NO TRADE.

Every thesis must identify what would make it wrong.

# 18. CANONICAL STRATEGY REGISTRY & EXECUTION POLICY

| **ID** | **Strategy** | **Default mode** | **Unlock condition** |
| --- | --- | --- | --- |
| S1 | Buyback + Value + Quality | Paper / Semi-auto | OOS + walk-forward + robustness + risk |
| S2 | Earnings Surprise + Revisions + Momentum | Paper / Semi-auto | OOS + event timing + cost |
| S3 | Macro Regime / ETF Rotation | Paper / Semi-auto | regime robustness |
| S4 | Medium-term Momentum | Paper / Semi-auto | factor overlap + OOS |
| S5 | Event / Supply-chain | Alert / Semi-auto | causal evidence + market confirmation |
| S6 | Options / Volatility | Alert / Semi-auto | Greeks + liquidity + max loss |
| S7 | Corporate Insider | Alert | source/context validation |
| S8 | Congress PTR | Alert | disclosure-lag aware |
| S9 | Political / Trump headlines | Alert | official status + transmission map |
| S10 | Intraday social headline | Alert only | no social-only execution |
| S11 | Small-cap squeeze | Alert only | no default auto |
| S12 | 0DTE speculation | Alert only | no default auto |

| **Registry rule** S1–S12 are immutable IDs. X Researcher is an intelligence module/source stream, not S10. ACL, API, backtest, audit and execution all reference strategy_id. |
| --- |

# 19. LONG / SHORT / PAIR / HEDGE DECISION FRAMEWORK

| **Type** | **Eligibility** |
| --- | --- |
| LONG | positive thesis + valuation/timing support + risk pass |
| SHORT | negative thesis + catalyst + borrow/liquidity + squeeze controls |
| PAIR | common causal driver + long beneficiary / short loser + hedge ratio |
| HEDGE | defined portfolio risk reduction + predefined cost |
| NO TRADE | already priced-in / insufficient evidence / excessive risk |

# 20. PORTFOLIO RISK ENGINE

Gross Exposure; Net Exposure; Beta; Sector/Country concentration; Factor exposure; Currency exposure; Commodity exposure; Volatility; VaR; Expected Shortfall; Drawdown; Liquidity.

Risk Agent can veto. Execution Agent cannot override Risk Agent.

Position sizing should target risk contribution, not only notional dollars.

# 21. DASHBOARD UX & INFORMATION ARCHITECTURE

| **#** | **Dashboard** | **Purpose** |
| --- | --- | --- |
| 1 | Global Monitor | World view |
| 2 | Market Regime | Growth/inflation/liquidity/credit/volatility |
| 3 | Opportunity Radar | Candidates |
| 4 | Fundamental Research | Company economics |
| 5 | Corporate Actions | Buybacks and capital actions |
| 6 | Event Transmission | Causal graphs |
| 7 | Earnings | Expectations + reaction |
| 8 | X / Expert Watch | Researcher watchlists |
| 9 | Policy Monitor | Trump/White House |
| 10 | Congress Trades | PTR |
| 11 | Options & Vol | Volatility/hedges |
| 12 | Portfolio Risk | Risk cockpit |
| 13 | Alerts Center | L0-L4 |
| 14 | Strategy Lab | Backtest/paper trade |
| 15 | Execution | Order/risk/audit |

Every dashboard supports filters, saved views, watchlists, date range, source filters, export, drill-down and responsive layout. Global Monitor locations should open current signals, latest English sources, entities, possible transmission paths, and linked instruments.

# 22. GLOSSARY / QUESTION-MARK SYSTEM CONTRACT

Implement one central glossary registry consumed by every frontend metric component. Desktop hover shows a compact tooltip; mobile click opens help popover.

| **Field** | **Required behavior** |
| --- | --- |
| term_id | stable immutable ID |
| display_name | UI label |
| category | taxonomy |
| short_definition | one sentence |
| full_definition | detailed |
| formula | formula/rule |
| unit | unit |
| example | concrete example |
| interpretation | how to read high/low |
| why_it_matters | decision relevance |
| source/source_url | method/data source |
| as_of | timestamp |
| update_cadence | refresh frequency |
| caveats | limitations |
| related_terms | linked IDs |
| methodology_version | calculation version |

Hard validation: a UI metric/score/badge/status/risk measure/strategy without a glossary entry is a build failure.

# 23. BACKTESTING & VALIDATION STANDARD

Point-in-time; no look-ahead; survivorship control; corporate-action handling.

Transaction cost and short-cost assumptions.

Walk-forward train/validate/test/forward.

Event timestamp fidelity.

Ablation studies.

Never optimize and evaluate on the same period.

Backtest UI must show CAGR, volatility, Sharpe, Sortino, max drawdown, hit rate, profit factor, turnover, holding period, exposure, transaction-cost drag, tail loss, regime performance, and out-of-sample period.

# 24. AI AGENT ARCHITECTURE

| **Agent** | **Permission** |
| --- | --- |
| Source Scout | No trading |
| Filing Agent | No trading |
| Event Agent | No trading |
| Causal Agent | No trading |
| Research Agent | No direct execution |
| Signal Agent | Signal candidate only |
| Risk Agent | Veto authority |
| Execution Agent | Approved orders only |
| Audit Agent | No trading |

LLMs are for extraction, linkage, synthesis and hypothesis generation. Deterministic/quantitative models are used for valuation calculations, factor calculations, risk, sizing and execution eligibility.

# 25. AUDITABILITY / OBSERVABILITY

Every signal: signal_id, family_id, strategy_id, observation IDs, rule version, score, direction, generated_at, valid_from, evidence independence, source quality, execution eligibility.

Every order: decision_id, strategy_id, signal_ids, thesis_id, portfolio_snapshot_id, risk_check_id, approval state, broker, instrument, side, quantity, order_type, max_loss, timestamps, fills, slippage, final status.

Monitor source freshness, ingestion failures, parsing confidence, queue lag, order failures, broker connection state, and risk vetoes.

# 26. HARD SAFETY / DATA INTEGRITY

No fake live data.

No delayed disclosure represented as current.

No political persuasion.

No social-only auto trade.

No backtest performance without PIT controls.

No order without risk/liquidity/strategy gate.

Risk Score: higher = worse. Positive scores: higher = better.

Paper/live isolation.

Kill switch + duplicate-order protection + idempotent order handling.

# 27. ENGINEERING BASELINE & PROVIDER DECISIONS

| **Layer** | **Canonical decision** |
| --- | --- |
| Frontend | Next.js + React + TypeScript |
| Backend | Python + FastAPI + Pydantic |
| DB | PostgreSQL + TimescaleDB |
| Object store | S3-compatible |
| Cache/queue | Redis |
| US equity price feed | Massive (formerly Polygon.io); current listed Stocks Advanced $199/month individual; Business separately licensed for customer-facing redistribution |
| Secondary price feed | Alpaca; Basic free with IEX real-time equities; Algo Trader Plus listed $99/month |
| Production broker | Interactive Brokers API adapter |
| Paper/developer broker | Alpaca API adapter |
| Macro | FRED + ALFRED |
| Filings | SEC data.sec.gov submissions/XBRL |
| English news prototype | GDELT + public English RSS/official feeds |
| Social/X | Official X API / licensed access only |
| Deployment | Containers + managed DB + secret manager + CI/CD |
| Scheduling | Scheduler + queue + retry/backfill/DLQ/freshness monitoring |

Current commercial assumptions are snapshots and must be re-verified before provisioning. Provider terms may change. Customer-facing market-data display/redistribution can require a business/commercial license.

## 27.1 Budget Guardrails, Licensing & Cost Controls

Use explicit engineering budgets rather than allowing provider spend to drift. These are internal planning caps, not vendor price guarantees. Re-verify all vendor pricing, usage units, redistribution rights and rate limits before provisioning or launch.

| Resource | Current/reference assumption | MVP budget guardrail | Control |
| --- | --- | --- | --- |
| US equity market data | Massive Stocks Advanced listed at $199/month for an individual plan; Business listed separately for customer-facing redistribution. | Budget to the applicable licensed tier; do not assume the individual plan permits redistribution. | Provision only after license check; alert at 80/100% of monthly budget. |
| Secondary market data | Alpaca Basic listed as free with IEX real-time equities; Algo Trader Plus listed at $99/month. | Use as redundancy/development feed; initial budget <= $100/month before validation. | Provider abstraction; stale-feed and discrepancy alerts. |
| X / researcher data | Official X Developer Platform uses consumption-based billing; actual cost depends on usage. | Set an internal MVP hard cap of $100/month, with 70/90/100% spend alerts. | Usage meter + budget circuit breaker; no core dependency on unauthorized scraping. |
| English news | Prototype with GDELT/public English RSS and official feeds; premium licensed feeds later. | $0 prototype target; reserve separate quote-based budget for premium redistribution/licensing. | Source Registry must store license/access status. |
| Cloud / infrastructure | Engineering planning assumption; provider prices vary. | Target $100–$300/month for early single-user MVP, excluding market/news/X licensing. | Cost dashboard + daily/weekly/monthly thresholds; re-estimate after load test. |

# 28. MINIMUM DATA SOURCE CONTRACTS

| **Object** | **Minimum fields** |
| --- | --- |
| MarketPriceObservation | instrument_id, venue, bid, ask, last, size, volume, currency, published_at, received_at, source_id, feed_status |
| FinancialFact | entity_id, metric_id, value, unit, currency, fiscal_period, period_end, filed_at, accession_id, source_id, vintage, restated_flag |
| NewsEvent | event_id, source_id, tier, title, author, url, published_at, updated_at, language, entities, tickers, type, confidence, duplicate_group_id |
| SocialPost | post_id, author_id, handle, posted_at, permitted representation, URL, entities, tickers, topic, engagement, license status, confidence |
| PTRTrade | filer_id, chamber, trade_date, notification_date, filing_date, lag_days, asset, ticker, transaction_type, owner, amount_range, URL, reported_trade_flag |
| InsiderTrade | issuer_id, insider_id, filing_date, trade_date, form_type, transaction_code, shares, price, 10b5-1_flag, post_transaction_ownership, URL |
| Signal | signal_id, family_id, strategy_id, observation_ids, rule_version, score, direction, generated_at, evidence_independence, source_quality, execution_eligibility |
| TradeDecision | decision_id, strategy_id, signal_ids, thesis_id, portfolio_snapshot_id, risk_check_id, approval_state, broker, instrument, side, quantity, order_type, max_loss, timestamps |

# 29. PHASE 0–6 IMPLEMENTATION PLAN

| **Phase** | **Build** | **Acceptance / exit criteria** |
| --- | --- | --- |
| 0 | Data/schema/glossary/governance | Real market + SEC + macro + English news; PIT works; provenance and glossary validation pass; no mock-live confusion |
| 1 | Fundamental/Buyback/Earnings | Filing reconciliation; authorization vs actual repurchase; valuation assumptions; paper journal |
| 2 | Macro/Momentum/Risk | Regime reproducibility; factor versioning; risk veto deterministic; walk-forward available |
| 3 | World/Physical/Policy | Causal evidence; policy lifecycle; no event-only execution |
| 4 | X Researcher/Congress PTR | Source provenance; thesis-change; reported-trade wording; lag visible |
| 5 | Options/Broker | Liquidity/max-loss; duplicate protection; paper/live isolation; kill switch; reconciliation |
| 6 | Selective Auto | OOS + walk-forward + costs + robustness + canary + rollback + 100% audit trace |

# 30. STRATEGY PERMISSION MATRIX

| **Strategy** | **Default** | **Auto-unlock** |
| --- | --- | --- |
| S1 | Paper / Semi-auto | OOS + walk-forward + robustness + risk |
| S2 | Paper / Semi-auto | OOS + event-timing + costs |
| S3 | Paper / Semi-auto | regime robustness |
| S4 | Paper / Semi-auto | factor overlap + OOS |
| S5 | Alert / Semi-auto | causal + market confirmation |
| S6 | Alert / Semi-auto | Greeks + liquidity + max loss |
| S7 | Alert | context validation |
| S8 | Alert | lag-aware only |
| S9 | Alert | official status + transmission |
| S10 | Alert only | no social-only execution |
| S11 | Alert only | no default auto |
| S12 | Alert only | no default auto |

# 31. BUILD OUTPUT CONTRACT

For every milestone, return: implementation status; repository/file tree; database migrations; API contract; provider adapters; UI route list; working dashboard; tests; acceptance results; known gaps; data freshness status. Never declare complete because a UI mock renders.

Before any execution capability is enabled, output a validation report containing strategy_id, sample period, OOS period, walk-forward design, transaction-cost assumptions, liquidity assumptions, risk limits, and approval state.

# 32. APPENDICES

## 32.1 Glossary seed

| **Term** | **Short definition** | **Formula / rule** | **Direction** |
| --- | --- | --- | --- |
| Buyback Intensity | Actual repurchases relative to market cap or FCF | Repurchase Value / Market Cap or FCF | Higher = more intensive, not automatically better |
| Net Share Reduction | Gross share repurchase effect net of issuance/dilution | Buyback shares - dilution shares | Higher = greater per-share benefit |
| Thesis Score | Strength of economic/investment thesis | model-specific 0–100 | Higher = better |
| Timing Score | Strength of current market confirmation | model-specific 0–100 | Higher = better |
| Execution Score | Order quality based on liquidity/spread/risk | model-specific 0–100 | Higher = better |
| Risk Score | Risk severity | model-specific 0–100 | Higher = worse |
| Disclosure Lag | Delay between trade date and filing date | Filing Date - Trade Date | Higher = staler |
| Market Confirmation | Extent to which price/volume/options support thesis | model-specific | Higher = more confirmation |
| Catalyst | Future identifiable event that can reprice asset | event/date | N/A |
| Invalidation | Condition that makes thesis fail | explicit rule/threshold | N/A |
| Regime | Current macro/market environment state | state machine | N/A |
| Tail Risk | Low-probability high-impact/fragility risk | risk class | N/A |
| Point-in-Time | Use only information known at that timestamp | historical information set | N/A |
| Look-ahead Bias | Future information leaking into past test | validation failure | N/A |
| Survivorship Bias | Excluding dead/delisted names | validation failure | N/A |
| VaR | Loss threshold at stated confidence | distribution-dependent | N/A |
| Expected Shortfall | Average loss beyond VaR | conditional tail loss | N/A |
| Gross Exposure | Absolute long + short notional / capital | sum(abs(market values))/capital | Higher = more leverage |
| Net Exposure | Long minus short notional / capital | (long-short)/capital | Higher = more directional |
| IV | Option-implied volatility | inferred from option price | Higher = more implied vol |
| IV Percentile | Current IV percentile in historical distribution | percentile(IV history) | Higher = more expensive relative context |
| Skew | Difference/shape of IV across strikes | surface-derived | Context dependent |
| Reported Trade | Publicly disclosed trade event | official disclosure record | Not current position |
| Policy Status | Lifecycle of policy action | state machine | N/A |
| Source Tier | Evidence reliability tier | Tier 1–4 | Higher tier = stronger source quality |

## 32.2 Hard prohibitions

Do not fabricate data.

Do not scrape where licensing forbids it.

Do not bypass risk or execution permission.

Do not use political or social content as sole automatic trade instruction.

Do not present model fair value as certainty.

Do not collapse positive-direction and negative-direction scores without clear normalization.

## 32.3 External entry points

Massive: https://www.massive.com/stocks

Alpaca Market Data: https://docs.alpaca.markets/us/v1.1/docs/about-market-data-api

Interactive Brokers Paper Trading: https://www.interactivebrokers.com/docs/tws-api/doc/notes-limitations/limitations/paper-trading

SEC EDGAR APIs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces

FRED / ALFRED: https://fred.stlouisfed.org/docs/api/fred/

X Developer Platform: https://developer.x.com/

House Ethics: https://ethics.house.gov/financial-disclosure/

U.S. Senate Public Disclosure: https://www.senate.gov/legislative/Public_Disclosure/financial-disclosure.htm

White House Presidential Actions: https://www.whitehouse.gov/presidential-actions/

World Monitor: https://www.worldmonitor.app/

GDELT: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/amp/

AI Global Market Intelligence & Semi-Automated Trading Platform | Master Build Prompt | v2.0 | 2026-10-04