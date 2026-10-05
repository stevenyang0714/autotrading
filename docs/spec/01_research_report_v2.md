研究報告：AI Global Market Intelligence & Semi-Automated Trading Platform

*從「看到世界」到「理解傳導」再到「可驗證交易」的完整產品藍圖*

**Version 2.0 | Research / build snapshot: 2026-10-04**

# Executive Summary

最終產品原則是「360-degree intelligence, selective execution」：研究層可以全面監測全球總體、個體、政策、實體世界、社群、公司行動與市場資料；交易層只允許少數經過 point-in-time、OOS、walk-forward、成本、流動性與風險驗證的 strategy sleeves 進入半自動或自動執行。

新增的英文最新資訊、指定 X 研究員、Trump / White House、U.S. Congress PTR、即時價格、財報、估值、庫藏股與因果交易，全部可以放在既有十大家族下；不要再增加第 11–13 類。來源與資料形態是可擴張的，Signal Family 應保持穩定。

| **最重要的產品區分** Research signal ≠ Trading signal ≠ Execution permission. 每一個候選都必須回答：What happened? Why does it matter? Who is exposed? Has the market priced it? Is there a validated trade now? |
| --- |

# 1. 新增需求與十大家族的最終歸屬

| **需求** | **Canonical 歸屬** | **產品規則** |
| --- | --- | --- |
| 英文網站最新資訊 | 9. Geopolitical / Policy / Social Intelligence + Data Foundation | source registry + freshness SLA；英文-first；secondary discovery、primary confirmation |
| Trump / White House | 9. Geopolitical / Policy / Social Intelligence | policy lifecycle：statement → proposal → signed → effective → implementation；不得把人物言論當投資權威 |
| 指定 X 股票研究員 | 9. Geopolitical / Policy / Social Intelligence | watchlist、ticker/entity extraction、thesis-change、author calibration；不是獨立 strategy ID |
| U.S. Congress stock trades | 7. Positioning & Flows | Reported Trade；trade date、filing date、lag、amount range；不得呈現 current position |
| 即時股價 / volume | 5. Price / Trend / Factor + Data Foundation | market feed 是 timing/execution 基礎，不能由 agent 猜來源 |
| 財報自動更新 | 3. Fundamental & Valuation | SEC/issuer filings、XBRL、版本化、point-in-time |
| 股票價值 vs 價格 | 3. Fundamental & Valuation | DCF、reverse DCF、relative valuation、FCF yield、ROIC、SOTP；fair value 永遠帶 assumptions |
| Black Swan / crisis | 10. Tail Risk / Regime Stress | fragility detection，不做 black-swan prediction |
| Buyback | 2. Corporate Actions & Capital Structure | authorization ≠ actual repurchase；加入 dilution、FCF、valuation、timing |
| El Niño / 火災 / supply shock | 8. Alternative / Physical / Supply Chain | Event → Physical → Supply/Demand → Commodity → Industry → Company → P&L → Valuation → Market → Trade |

# 2. 十大 Signal Families（Canonical）

| **#** | **Family** | **Coverage** |
| --- | --- | --- |
| 1 | Macro Regime | Fed/ECB/BoJ/PBoC；inflation；growth；PMI；employment；real rates；yield curve；liquidity；credit |
| 2 | Corporate Actions & Capital Structure | buyback；dividend；M&A；spin-off；SEO/rights；IPO；convertible；debt/refinancing；capital structure |
| 3 | Fundamental & Valuation | financial statements；FCF；ROIC/ROE；margins；quality；leverage；DCF；reverse DCF；multiples；SOTP |
| 4 | Earnings & Estimates | surprise；guidance；revisions；dispersion；PEAD；peer information transfer |
| 5 | Price / Trend / Factor | momentum；breakout；relative strength；moving averages；value/size/profitability/investment factors |
| 6 | Options & Volatility | IV；RV；IV percentile；skew；term structure；expected move；Greeks；hedging |
| 7 | Positioning & Flows | short interest；borrow；institutional/ETF flows；CFTC COT；dealer positioning；Congress PTR |
| 8 | Alternative / Physical / Supply Chain | weather；fires；satellite；shipping；ports；power；commodity；traffic；industrial activity |
| 9 | Geopolitical / Policy / Social Intelligence | Trump/White House；elections；sanctions；wars；X researchers；English news；analyst discourse |
| 10 | Tail Risk / Regime Stress | liquidity；credit；volatility；correlation；funding；FX；cross-asset dislocation；fragility |

# 3. 基礎研究層：Price、Value、Financials、Expectations

這一層不是附加功能，而是所有 event / social / policy signal 最後都必須落地的 company economics layer。每家公司要有 persistent Research Record，不是只有 quote card。

| **Module** | **Required fields** | **Why it matters** |
| --- | --- | --- |
| Income statement | Revenue; gross profit/margin; operating income/margin; EBITDA where relevant; net income; EPS | earnings power and operating leverage |
| Balance sheet | cash; total debt; net debt; working capital; PP&E; intangibles | liquidity and capital structure |
| Cash flow | CFO; capex; FCF; FCF conversion; working capital | earnings quality and capital allocation |
| Per-share | diluted shares; SBC; buyback; issuance; option dilution | net economics to shareholders |
| Quality | ROIC; ROE; margin stability; FCF quality | business economics |
| Valuation | P/E; EV/EBITDA; EV/Sales; P/B when relevant; FCF yield; earnings yield; DCF; reverse DCF; SOTP | price versus model value |
| Expectations | consensus EPS/revenue; revisions; dispersion; guidance; event dates | what market expected before the event |

| **Fair-value display contract** Every fair-value card must show method, assumptions, discount rate/terminal assumptions where applicable, scenario range, current price, implied upside/downside, margin of safety, model date, and source-data as-of date. Never display fair value as an objective fact. |
| --- |

# 4. Buyback / Capital Allocation Engine

INSEAD CFP 的 payout policy 將 dividend 與 buyback 分開：dividend 不改變 shares outstanding，而 buyback 會降低 shares outstanding；在非完美市場中，payout policy 又涉及 agency cost、資訊不對稱與 signaling。這使 buyback 成為非常適合系統化研究的 corporate signal。

| **Term** | **Definition** | **System rule** |
| --- | --- | --- |
| Authorization | 公司公告的可回購額度 | announcement only；不得當成已執行 |
| Actual repurchase | 實際買回 shares / dollars | high-weight signal |
| Repurchase intensity | repurchase value / market cap 或 FCF | 衡量力度 |
| Net share reduction | buyback effect 減 SBC / issuance dilution | 比 gross buyback 更重要 |
| FCF funding | 以持續性自由現金流支持回購 | 避免用借債製造假訊號 |
| Valuation context | price vs DCF / FCF yield / multiples | 避免高估值高位回購 |
| Timing discipline | 公司過往在高估/低估時的實際回購 | 建立 company-specific prior |

初始化 Buyback Quality Score（可版本化、可回測）= 30% undervaluation + 20% actual repurchase intensity + 15% FCF quality + 10% balance-sheet strength + 10% historical discipline + 10% net share-count impact + 5% management/insider alignment。上線前必須 walk-forward 驗證。

# 5. Event → Commodity → Industry → Company Causal Engine

flagship workflow：Event → Physical condition → Supply/Demand → Commodity/Input Price → Industry Economics → Company Exposure → Revenue/Cost/Margin/EPS/FCF → Valuation Gap → Price Confirmation → Trade Candidate。

| **Stage** | **Required evidence** | **Example** |
| --- | --- | --- |
| Physical trigger | weather anomaly; fire; flood; earthquake; port/mine outage | satellite fire hotspot + rainfall anomaly |
| Supply / demand | production, inventories, logistics, capacity, power | mine output estimate + port congestion |
| Commodity | futures/spot/curve | nickel/palm oil/cocoa/coffee/oil/gas |
| Industry | input cost, utilization, pricing power | processor margin compression/expansion |
| Company | revenue exposure, COGS sensitivity, geography | company exposure map |
| Financial impact | EBITDA/FCF/EPS sensitivity | scenario range |
| Market confirmation | price, volume, options, relative strength | is market already pricing it in? |
| Trade | long/short/pair/hedge | only after strategy + risk gate |

| **Example: El Niño / Indonesia** The platform should not jump from “El Niño” to a ticker. It must test whether the physical shock is real, whether supply is actually constrained, whether the commodity market confirms it, and which companies have enough economic exposure for the thesis to matter. |
| --- |

# 6. Trump / White House Policy Intelligence

把政治人物視為 market-moving information source，而不是投資權威。任何 policy item 都要有 policy_status、jurisdiction、affected goods/sectors/countries、effective date、implementation status、direct/second-order exposure、linked companies/instruments。

| **Policy state** | **Meaning** | **Trade treatment** |
| --- | --- | --- |
| Statement | 口頭/社群/公開表態 | alert / discovery |
| Proposal | 正式提出但未生效 | scenario only |
| Signed action | 已簽署行政/正式文件 | high-confidence event with legal/source check |
| Effective | 規則/措施已生效 | can enter causal model |
| Implementation | 開始執行，實體效果可觀察 | stronger confirmation |
| Challenged / modified | 有訴訟、修改或限制 | recalculate scenario |
| Expired / replaced | 失效或被取代 | remove from active thesis |

# 7. English-first News / Web Intelligence

External market/news intelligence 的 primary language = English-first。系統保存原始標題、source、author、published_at、updated_at、URL、language、entities、tickers、commodities、countries、policy entities，並做 syndicated/copy deduplication。

Primary source confirms facts; professional media accelerates discovery/context; specialist/social is early signal; anonymous/repost is weak lead.

任何 derived summary 必須保留原始 source link 與時間；不可把 paywalled article 全文當作資料庫內容。

Prototype 可採 GDELT + public English RSS/official feeds；商業版用 licensed premium feeds，所有 provider 都透過 Source Registry。

# 8. X / Researcher Intelligence

X 是 expert discourse / attention layer。使用者可以建立 account/list/keyword/ticker/sector/theme watchlist。核心不是單句 sentiment，而是「同一作者對同一 ticker/主題的 thesis change」。

| **Feature** | **Definition** | **Rule** |
| --- | --- | --- |
| Watchlist | 使用者指定的研究員/作者/列表 | user-controlled |
| Entity extraction | ticker/company/commodity/country/policy extraction | NER + resolver |
| Thesis change | 與作者歷史觀點比較後的立場/論證變化 | high-value feature |
| Evidence quality | 引用 filing/data/first-hand evidence 的程度 | source-quality modifier |
| Engagement | views/reposts/replies/likes when available | attention multiplier only |
| Author calibration | historical thesis vs subsequent outcome | source-specific reliability; no idolization |

# 9. U.S. Congress PTR Monitor

Congressional trades 必須標示 Reported Trade。House 與 Senate 的 PTR 都存在 disclosure lag；金額通常為區間，因此更適合 slow-moving idea generation，而不是即時 copy trading。

| **Field** | **Definition** |
| --- | --- |
| Trade date | 交易實際發生日 |
| Notification date | 取得交易通知日期，若可得 |
| Filing date | 公開披露日 |
| Disclosure lag | filing date - trade date |
| Amount range | 官方披露的金額區間，不自行猜精確值 |
| Owner | self / spouse / dependent child / other reported owner |
| Direction | buy / sell / exchange；不推斷意圖 |
| Staleness | 距交易日/披露日多久 |

# 10. Corporate Insider Engine

Form 4 應區分 open-market purchase/sale、option exercise、grant、vesting、tax withholding、10b5-1 plan、gift 等 transaction code。insider sale 不能機械地標成 bearish。10b5-1 欄位應顯示「與否」，不能顯示韓文或未解析狀態。

# 11. Earnings Intelligence

Earnings engine 要看 surprise relative to expectations，而不是只看 beat/miss。至少同時處理 consensus、actual、guidance、revisions、price/volume/IV reaction、peer information transfer。

| **Signal component** | **What to compute** |
| --- | --- |
| Fundamental surprise | EPS, revenue, margin, FCF surprise versus pre-event expectation |
| Forward revision | consensus estimate changes after release |
| Guidance | revenue/margin/capex/bookings and other forward indicators |
| Market confirmation | post-event price/volume/IV/relative strength |
| Valuation context | price versus fair-value and historical valuation |
| Peer transfer | supplier/customer/competitor earnings information transfer |

# 12. Price / Trend / Factor

第一階段優先中期可解釋訊號：3–12 month momentum、relative strength、breakout、moving-average structure、value、size、profitability、investment、industry/sector relative strength。Intraday pattern 不是 MVP 優先。

# 13. Options / Volatility

INSEAD CFP 的 derivatives framework 可轉成 pricing / hedging 基礎。平台必須區分 realized volatility 與 implied volatility；historical volatility 不必然是 future volatility 的最佳估計。

| **Metric** | **Definition** | **Use** |
| --- | --- | --- |
| Realized vol | 歷史實際波動率 | history |
| Implied vol | 由 options market price 反推的波動率 | market expectation |
| IV percentile | 目前 IV 在歷史分布中的 percentile | context |
| Skew | 不同 strike 的 IV 結構 | tail demand |
| Term structure | 不同到期日 IV | event/regime |
| Expected move | 由 IV 與 maturity 推算的市場隱含區間 | earnings/event |
| Delta/Gamma/Vega/Theta | option Greeks | risk/hedge |

| **Execution restriction** 不自動交易 illiquid options、wide-spread contracts 或 0DTE speculation。第一階段以 analytics、defined-risk strategy 與 portfolio hedge 為主。 |
| --- |

# 14. Tail Risk / Fragility Engine

Tail engine 不預測黑天鵝，而是偵測 fragility。核心 inputs：credit spreads、VIX/term structure、funding/liquidity、yield-curve dislocation、cross-asset correlation、FX stress、commodity shock、shipping disruption、bank stress。

| **Regime** | **Definition** | **Default response** |
| --- | --- | --- |
| Normal | stress indicators mostly normal | normal strategy eligibility |
| Elevated | some stress metrics deteriorate together | reduce new high-beta exposure |
| High | multi-asset stress converges | increase hedge / reduce gross |
| Crisis | liquidity/volatility dislocation | execution-first; stop nonessential new trades |

# 15. Signal Convergence

| **Level** | **Meaning** | **Action** |
| --- | --- | --- |
| L0 Information | single event/signal | record only |
| L1 Watch | multiple related signals | watchlist |
| L2 Thesis | multiple independent signals + causal chain | research thesis |
| L3 Trade Candidate | thesis + market confirmation + strategy trigger | paper/review |
| L4 Execution Ready | L3 + risk + liquidity + sizing + compliance | order preparation |

「獨立」是關鍵。Reuters、CNBC、X repost 若來自同一 underlying source，不可被當成三個獨立證據。文章數量不等於 evidence count。

# 16. Investment Thesis Card

| **Field** | **Required content** |
| --- | --- |
| Asset | ticker/instrument/market |
| Thesis | 1–2 sentence causal statement |
| Evidence | 3–7 most important facts with source/time |
| Catalyst | future identifiable event not fully priced-in |
| Valuation | current price vs fair-value range + assumptions |
| Timing | momentum / market reaction / technical confirmation |
| Risk | invalidation conditions |
| Position | long / short / pair / hedge |
| Sizing | target risk contribution, not only $ amount |
| Scores | Thesis, Timing, Execution, Risk, Data Freshness, Source Quality |

# 17. Strategy Universe — Canonical S1–S12

| **ID** | **Strategy** | **Default priority** | **Default execution** |
| --- | --- | --- | --- |
| S1 | Buyback + Value + Quality | High | Paper / Semi-auto; auto only after validation |
| S2 | Earnings Surprise + Revisions + Momentum | High | Paper / Semi-auto; auto only after validation |
| S3 | Macro Regime / ETF Rotation | High | Paper / Semi-auto; auto only after validation |
| S4 | Medium-term Momentum | High | Paper / Semi-auto; auto only after validation |
| S5 | Event / Supply-chain | Medium | Alert / Semi-auto |
| S6 | Options / Volatility | Medium | Analytics / hedge / semi-auto |
| S7 | Corporate Insider | Medium | Alert + confirmation |
| S8 | Congress PTR | Low-Medium | Alert / slow signal |
| S9 | Political / Trump headlines | Low-Medium | Alert / causal analysis |
| S10 | Intraday social headline | Low | Alert only |
| S11 | Small-cap squeeze | Low | Alert only |
| S12 | 0DTE speculation | Low | Alert only |

| **Canonical ID rule** S1–S12 are immutable and globally unique. X Researcher is a source/intelligence module, not S10. All ACL, API, backtest, audit, and execution permissions reference strategy_id rather than display labels. |
| --- |

# 18. Long / Short / Pair / Hedge

| **Type** | **Eligibility** | **Default policy** |
| --- | --- | --- |
| LONG | positive thesis + valuation/timing support + risk pass | can become auto-eligible after validation |
| SHORT | negative thesis + catalyst + borrow/liquidity + squeeze controls | semi-auto only for large/liquid names |
| PAIR TRADE | long beneficiary + short loser with common causal driver | preferred event-driven structure |
| HEDGE | defined portfolio exposure reduction | auto-eligible only if predefined |
| NO TRADE | thesis valid but already priced-in or risk too high | explicitly display NO TRADE |

# 19. Portfolio Risk Engine

| **Metric** | **Definition** | **Purpose** |
| --- | --- | --- |
| Gross exposure | sum absolute market values / capital | leverage background |
| Net exposure | long market value - short market value / capital | directional exposure |
| Beta | portfolio sensitivity to benchmark | market risk |
| Sector/Country concentration | portfolio concentration by sector/country | thesis overlap |
| Factor exposure | value/momentum/quality/size etc. | hidden factor bets |
| Currency exposure | net exposure by currency | FX risk |
| Commodity exposure | economic exposure by commodity | physical shock risk |
| Volatility | portfolio/position volatility | sizing |
| VaR | loss threshold at stated confidence | risk reference, not worst loss |
| Expected Shortfall | average loss beyond VaR | tail conditional loss |
| Max Drawdown | maximum peak-to-trough decline | historical risk |
| Liquidity | ADV/spread/market impact | execution feasibility |

# 20. Data Source Hierarchy

| **Tier** | **Examples** | **Rule** |
| --- | --- | --- |
| Tier 1 | SEC/EDGAR; licensed market-price/venue feeds (e.g., Massive); issuer filings; FRED/ALFRED; Treasury; CFTC; White House; House/Senate disclosure; official agency data | trade-critical confirmation |
| Tier 2 | Reuters; FT; WSJ; Bloomberg; AP; CNBC; Economist; licensed research/data | fast discovery/context; license required |
| Tier 3 | X research accounts; specialist blogs/newsletters; community | early signal / attention |
| Tier 4 | anonymous source; repost; unverified social | weak lead only; never sole execution evidence |

Trade-critical price feeds, official filings and macro observations are Tier 1 evidence when licensed/available; provider access and licensing are first-class metadata. Unauthorized scraping is not a core dependency. Customer-facing redistribution rights must be explicitly licensed.

# 21. Dashboard Information Architecture

| **Dashboard** | **Primary purpose** |
| --- | --- |
| 01 Global Monitor | World map + macro + geopolitics + weather + shipping + commodity |
| 02 Market Regime | growth/inflation/liquidity/credit/volatility/risk appetite |
| 03 Opportunity Radar | long/short/hedge candidates + convergence |
| 04 Fundamental Research | financials + valuation + quality + capital allocation |
| 05 Corporate Actions | buyback/dividend/M&A/SEO/convertible/insider |
| 06 Event Transmission | causal event → company graph |
| 07 Earnings | calendar + surprise + guidance + revisions + reaction |
| 08 X / Expert Watch | watchlists + mentions + thesis changes |
| 09 Policy Monitor | Trump/White House + tariffs + sanctions + critical materials |
| 10 Congress Trades | House/Senate PTR + lag + amount range |
| 11 Options & Vol | IV/skew/term structure/hedges |
| 12 Portfolio Risk | exposure + stress + drawdown + hedges |
| 13 Alerts Center | L0-L4 + rules + acknowledgement |
| 14 Strategy Lab | backtest + walk-forward + paper trade |
| 15 Execution | order preview + risk approval + broker + fills + audit |

# 22. Tooltip / Question-mark System Contract

每一個自訂 metric、ratio、score、badge、alert、strategy、risk measure、policy state 與 dashboard label 都必須有 ?。Desktop = hover compact tooltip；mobile = click/tap help popover。來源是 central Glossary Registry，不允許 page-specific ad hoc definitions。

| **Glossary field** | **Definition** |
| --- | --- |
| term_id | stable ID used by UI/API |
| display_name | human-readable label |
| category | signal / valuation / risk / execution / status etc. |
| short_definition | one-sentence definition |
| full_definition | detailed definition |
| formula | formula or rule where applicable |
| unit | %, currency, ratio, days, score etc. |
| example | one concrete example |
| interpretation | how to read high/low |
| why_it_matters | decision relevance |
| source | data/methodology source |
| source_url | source link |
| as_of | data/methodology timestamp |
| update_cadence | intraday/daily/per filing/etc. |
| caveats | limitations / ambiguity |
| related_terms | linked glossary IDs |
| methodology_version | calculation version |

| **Validation rule** A new UI metric without a Glossary Registry entry is a build failure. A metric tooltip must never silently disagree with the calculation implemented in code. |
| --- |

# 23. Backtesting Standard

Point-in-time data: only data knowable at the timestamp may enter the feature set.

No look-ahead bias: future information must never leak into historical decisions.

Survivorship bias control: include delisted/acquired names in historical universes.

Corporate actions: split, dividend, spin-off, delisting and symbol changes must be handled.

Transaction costs: commissions, spread, slippage, market impact.

Short costs: borrow fee, availability, locate when estimable.

Event timing: use actual announcement timestamp, not only calendar date.

Walk-forward validation: train → validate → test → forward.

Ablation: compare fundamental-only vs event vs market-confirmation configurations.

Never optimize and evaluate on the same period.

# 24. AI / Agent Architecture

| **Agent** | **Responsibility** | **Permission** |
| --- | --- | --- |
| Source Scout | English latest data, primary-source discovery, deduplication | No trading |
| Filing Agent | SEC/issuer filing parsing, structured financial facts, buyback/insider extraction | No trading |
| Event Agent | event classification, entity linking, policy status | No trading |
| Causal Agent | transmission graph + scenario candidates | No trading |
| Research Agent | fundamental research, valuation, peer comparison | No direct execution |
| Signal Agent | feature → signal candidates | Cannot bypass risk |
| Risk Agent | portfolio exposure, stress, sizing, veto | Can veto; cannot invent execution |
| Execution Agent | order preview, broker status, fill monitoring | Only approved orders |
| Audit Agent | decision trace and immutable event history | No trading authority |

# 25. Auditability / Observability

Every important object supports created_at, updated_at, source provenance, version, point-in-time retrieval where relevant. Every order must store decision_id, strategy_id, signal_ids, thesis_id, portfolio_snapshot_id, risk_check_id, approval state, broker, order details, timestamp, fills, slippage, final status. Decision trace completeness target = 100%.

# 26. Hard Safety / Data Integrity Rules

Never fabricate live prices, filings, news, X posts or portfolio positions.

Never present delayed congressional disclosures as current positions.

Never treat political statements as investment authority.

Never allow an unverified social signal to auto-execute alone.

Never publish a backtest result without point-in-time controls and cost assumptions.

Never place an order without risk gate, liquidity gate, strategy eligibility, and approval policy.

Risk Score direction: higher = worse / more risk. Do not average it directly with positive-direction scores without normalization.

NO TRADE is a valid outcome and should be explicit.

Paper and live environments must be isolated.

A kill switch must be available to block new orders and cancel/flatten according to configured emergency policy.

# 27. Engineering Baseline & Provider Decisions

| **Component** | **Decision** | **Current implementation note** |
| --- | --- | --- |
| Frontend | Next.js + React + TypeScript | desktop-first responsive dashboard |
| Backend | Python + FastAPI + Pydantic | typed domain/API contracts |
| Database | PostgreSQL + TimescaleDB | relational state + time series |
| Object storage | S3-compatible | raw artifacts, filings, event payloads, datasets |
| Cache / queues | Redis | cache, rate limit, jobs/locks; not source of truth |
| Primary US equity market data | Massive (formerly Polygon.io) | Current listed Stocks Advanced: $199/month individual, real-time, 20+ years history, quotes/trades/financials; Business plan separately licensed for customer-facing redistribution. Verify before provisioning. |
| Secondary US market data | Alpaca Market Data | Basic free with IEX real-time; Algo Trader Plus listed at $99/month with broader US equity coverage. Use same provider abstraction. |
| Production broker | Interactive Brokers | Primary production broker adapter; paper trading first. Keep broker abstraction. |
| Developer/paper broker alternative | Alpaca | Useful secondary paper/development adapter. |
| Macro | FRED + ALFRED | Use real-time periods/vintages. |
| Filings | SEC data.sec.gov submissions + XBRL | Preserve accession-linked history and revisions. |
| English news prototype | GDELT + official RSS/public English feeds | Premium licensed feeds later. |
| X | Official X Developer Platform / licensed access | Consumption-based pricing; cost is usage-driven. |
| Deployment | Containerized services + managed DB + secrets manager + CI/CD | separate local/staging/prod |
| Scheduling | Scheduler + queue | idempotent jobs, retry, backfill, DLQ, freshness SLA |

Current web validation (2026-10-04): Massive’s current stocks page lists individual Stocks Advanced at $199/month and Business at $2,499/month; Alpaca lists Basic as free with IEX-only real-time equities and Algo Trader Plus at $99/month; X documents pay-per-use billing; SEC documents real-time-ish submission/XBRL data APIs; FRED/ALFRED explicitly support real-time periods/vintages; IBKR documents paper trading through its API environment. These are time-sensitive and must be re-checked at build/provisioning time.

## 27.1 Budget Guardrails, Licensing & Cost Controls

Provider pricing and access terms are time-sensitive. The following are engineering planning guardrails, not commitments or quotations. Re-check pricing, entitlements, rate limits and redistribution rights at provisioning time.

| Resource | Current/reference assumption | MVP budget guardrail | Design control |
| --- | --- | --- | --- |
| US equity market data | Massive Stocks Advanced listed at $199/month for an individual plan; Business listed separately for customer-facing redistribution. | Choose the plan that matches the actual use/licensing model; do not assume individual access permits redistribution. | License check before deployment; budget/spend alert. |
| Secondary market data | Alpaca Basic listed as free with IEX real-time equities; Algo Trader Plus listed at $99/month. | Initial redundancy/development budget <= $100/month. | Compare feed quality; stale/discrepancy alerts. |
| X / researcher data | Official X Developer Platform uses consumption-based billing; actual spend is usage-driven. | Internal MVP hard cap $100/month; alerts at 70%, 90%, 100%. | Usage ledger + circuit breaker; licensed/API access only. |
| English news | GDELT/public English RSS/official feeds for prototype; premium feeds later. | $0 prototype target; premium media reserved for separate quote/licensing budget. | Store source license/access status; no paywall-text replication. |
| Cloud / infrastructure | Planning assumption; depends on deployment scale. | Target $100–$300/month for early single-user MVP, excluding external data licensing. | Monitor monthly spend; revise after load testing. |

# 28. Source Registry / Data Contracts

| **Object** | **Required minimum fields** |
| --- | --- |
| MarketPriceObservation | instrument_id; symbol; venue; bid; ask; last; size; volume; currency; published_at; received_at; source_id; feed_status; adjustment_status |
| FinancialFact | entity_id; metric_id; value; unit; currency; fiscal_period; period_end; filed_at; accession_id; source_id; vintage/revision metadata; restated_flag |
| NewsEvent | event_id; source_id; source_tier; title; author; url; published_at; updated_at; language; entities; tickers; event_type; confidence; duplicate_group_id |
| SocialPost | post_id; author_id; handle; posted_at; permitted representation; source_url; entities; tickers; topic; engagement; license status; confidence |
| PTRTrade | filer_id; chamber; trade_date; notification_date; filing_date; lag_days; asset; ticker; transaction_type; owner; amount_range; source_url; reported_trade_flag |
| InsiderTrade | issuer_id; insider_id; filing_date; trade_date; form_type; transaction_code; shares; price; 10b5-1_flag; post_transaction_ownership; source_url |
| Signal | signal_id; family_id; strategy_id nullable; observation_ids; rule_version; score; direction; generated_at; valid_from; evidence_independence; source_quality; execution_eligibility |
| TradeDecision | decision_id; strategy_id; signal_ids; thesis_id; portfolio_snapshot_id; risk_check_id; approval_state; broker; instrument; side; quantity; order_type; max_loss; created_at; user_id |

# 29. Phase 0–6 Implementation Plan and Acceptance Criteria

| **Phase** | **Scope** | **Deliverables** | **Exit criteria** |
| --- | --- | --- | --- |
| 0 | Data / schema / glossary | SEC + market + macro + English news; canonical IDs; PIT storage; audit trail | No fake live data; provenance; glossary validation; PIT query reproducible |
| 1 | Fundamental / Buyback / Earnings | Research record; valuation; actual repurchase; earnings/revisions; paper journal | Financial facts reconcile; buyback authorization/actual/net reduction separated; assumptions visible |
| 2 | Macro / Momentum / Risk | regime engine; factors; portfolio cockpit; ETF rotation | walk-forward backtest; deterministic risk veto; factor overlap visible |
| 3 | World / Physical / Policy | weather/fire/shipping/commodity; causal graph; Trump/White House states | causal evidence; policy lifecycle correctness; no direct execution from headline |
| 4 | X / Congress PTR | X watchlists; thesis change; PTR ingestion; lag analytics | source provenance; lag shown; reported-trade wording; X not sole trigger |
| 5 | Options / Broker | options analytics; hedge; order preview; IBKR adapter; reconciliation | liquidity/max-loss checks; duplicate-order protection; kill switch; paper/live isolation |
| 6 | Selective auto execution | only validated sleeves | OOS + walk-forward + cost + robustness + canary + rollback + 100% audit trace |

# 30. Strategy Permission Matrix

| **Strategy** | **Default mode** | **Unlock conditions** |
| --- | --- | --- |
| S1 Buyback + Value + Quality | Paper / Semi-auto | OOS + walk-forward + robustness + risk thresholds |
| S2 Earnings + Revisions + Momentum | Paper / Semi-auto | OOS + event-timing test + cost model |
| S3 Macro ETF Rotation | Paper / Semi-auto | regime robustness + turnover controls |
| S4 Medium-term Momentum | Paper / Semi-auto | factor-overlap + OOS stability |
| S5 Event / Supply-chain | Alert / Semi-auto | causal evidence + market confirmation + liquidity |
| S6 Options / Volatility | Alert / Semi-auto | Greeks + liquidity + defined max loss |
| S7 Corporate Insider | Alert | source/context validation |
| S8 Congress PTR | Alert | disclosure-lag aware; not current-position |
| S9 Political / Trump | Alert | official status + transmission mapping |
| S10 Intraday social | Alert only | never social-only execution |
| S11 Small-cap squeeze | Alert only | no default auto execution |
| S12 0DTE | Alert only | no default auto execution |

# 31. Research Conclusions

Broad intelligence is a strength only when paired with causal structure and evidence provenance.

Fundamental research is the base layer for interpreting social, policy, physical and corporate signals.

Buyback is strongest when actual repurchase, net share reduction, valuation and FCF quality agree; announcement alone is insufficient.

Congress PTR is delayed reported positioning, not current holdings.

Trump/White House is a policy transmission source, not a political recommendation engine.

X is an expert/attention signal and thesis-change source, not a replacement for fundamental research.

Black-swan logic should detect fragility, not claim to predict black swans.

The moat is Event Ontology + Entity Graph + Causal Graph + Signal Convergence + Strategy Registry + Risk Gate + Decision Trace.

# 32. External Research & Implementation References

World Monitor: https://www.worldmonitor.app/

Massive stocks / Polygon rebrand: https://www.massive.com/stocks

Massive pricing: https://www.massive.com/pricing?product=stocks

Alpaca market data: https://docs.alpaca.markets/us/v1.1/docs/about-market-data-api

Alpaca Trading API: https://docs.alpaca.markets/us/docs/trading-api

Interactive Brokers API / Paper Trading: https://www.interactivebrokers.com/docs/tws-api/doc/notes-limitations/limitations/paper-trading

SEC EDGAR APIs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces

FRED API: https://fred.stlouisfed.org/docs/api/fred/

FRED Real-Time Periods: https://fred.stlouisfed.org/docs/api/fred/realtime_period.html

X Developer Platform: https://developer.x.com/

House Ethics Financial Disclosure: https://ethics.house.gov/financial-disclosure/

Senate Public Disclosure: https://www.senate.gov/legislative/Public_Disclosure/financial-disclosure.htm

GDELT DOC 2.0: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/amp/

IMF El Niño research: https://www.imf.org/external/pubs/ft/fandd/2016/03/cashin.htm

INSEAD CFP Sessions 12–14: Payout policy, buybacks, information asymmetry, agency costs, derivatives; based on the user-provided course slides.

AI Global Market Intelligence & Semi-Automated Trading Platform | Research Design | v2.0 | 2026-10-04