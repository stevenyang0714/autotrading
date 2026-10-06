# Phase 1 — Fundamentals, buybacks, earnings, paper journal

**Status:** Approved by Steven on 2026-10-06, with the decisions below (ADR-020). Each sub-milestone still starts in plan mode and is approved before it is built.

**Goal:** for the universe equities, a persistent company Research Record:
- financials that reconcile to filings;
- valuation with visible assumptions;
- a buyback engine that tells authorization, actual repurchase and net share reduction apart, with versioned deterministic states;
- earnings events against the prior period, with the market's reaction;
- a paper journal of hypothetical decisions with a full trace, and in-app alerts.

**Phase 1 exit criteria:**
- ROADMAP: "Financial facts reconcile to filings; buyback states are versioned deterministic rules (errata E7); every fair value shows assumptions and as-of; paper journal records hypothetical decisions with full trace."
- 02 §29: "Filing reconciliation; authorization vs actual repurchase; valuation assumptions; paper journal".

**Entry gate:** met on 2026-10-06. Steven accepted the Phase 0 exit report, approved this file and answered the decisions below.

**Out of scope for Phase 1:**
- **Phase 2:** macro regime and momentum/factor engines, the Portfolio Risk cockpit, walk-forward backtests.
- **ADR-009 (Phase 3):** language-model extraction, unless P1-3 decides otherwise.
- **Phase 4:** X, Congress PTR, Form 4 insiders.
- **Phases 5–6:** options, any broker or order path, live trading.
- **Errata E3:** composite scores that mix risk with positive-direction scores.
- **OD-3:** consensus-based surprise.

Work one sub-milestone at a time, in order. Each one ends with the Build Output Contract and a `docs/STATUS.md` update. Every new metric, state and page ships with its glossary entry and Chinese hint in the same PR (ROADMAP standing rules).

---

## Decisions (Steven, 2026-10-06; ADR-020)

| # | Question | Decision |
|---|---|---|
| P1-1 | **OD-2:** alert delivery outside the app | In-app Alerts Center only for Phase 1; external delivery decided later |
| P1-2 | **OD-3:** point-in-time consensus provider | None for now. Consensus shows `Data unavailable`; earnings work is actual vs prior / YoY, guidance and price reaction (errata E6) |
| P1-3 | **Guidance from 8-K exhibits** | Rule-based: only explicit numeric guidance sentences (at most 300 characters each, with the link); otherwise "guidance not extracted". When the rules prove too narrow, Claude proposes switching to language-model extraction (ADR-009) for Steven's approval |
| P1-4 | **TRADE-READY** needs the Phase 2 risk check | Define the rule now; unreachable until the Phase 2 risk check exists, and the UI says so |
| P1-5 | **Buyback Quality Score** (02 §5 weights) before OD-7 | Show the composite **and** its components, labelled "default weights, unvalidated". The 5% management/insider component needs Form 4 data (Phase 4): it is left out, the other weights are rescaled to 100%, and the label says so. A positive-direction score only, never mixed with risk (errata E3) |
| P1-6 | **TradeDecision fields with no Phase 1 source** (`risk_check_id`, `portfolio_snapshot_id`, `broker`) | Nullable; `mode = paper` only; a database check forbids any broker value in Phase 1 |
| P1-7 | **Opportunity Radar** | Stays Phase 2 |
| P1-8 | **Universe** | Unchanged: 10 equities, with the 8 ETFs for market context |
| P1-9 | **Buyback state thresholds v0.1** (M1.4) | As proposed in M1.4: defaults, versioned, unvalidated (OD-7). M1.4 reports which state each universe company reaches so Steven can tune them |

---

## M1.1 Financial data completion and filing reconciliation
**Build**
- **New XBRL concepts.** Each is checked against the ten issuers' real filings before it is mapped. Candidates:
  - period-end shares outstanding (`dei:EntityCommonStockSharesOutstanding`, `us-gaap:CommonStockSharesOutstanding`);
  - shares repurchased (`StockRepurchasedDuringPeriodShares`, `TreasuryStockSharesAcquired`);
  - authorization and remaining amount (`StockRepurchaseProgramAuthorizedAmount1`, `StockRepurchaseProgramRemainingAuthorizedRepurchaseAmount1`);
  - D&A, stockholders' equity, dividends paid, interest expense, income tax, shares issued for compensation.
  - Same rule as ADR-013: a metric a company does not report stays unavailable and is never approximated.
- **Derived metrics,** with a versioned methodology. Each is computed only when every input exists:
  - free cash flow = operating cash flow − capex;
  - total debt = the stored components;
  - net debt = total debt − cash.
- **Splits:** store split events (Alpaca corporate actions, already fetched in M0.7). Show per-share history split-adjusted beside the reported values. This resolves the ADR-013 restatement-vs-split gap.
- **Quarterly and trailing-twelve-month tables:** 10-Q year-to-date values are differenced into quarters, keeping the provenance of both inputs.
- **Reconciliation job:** every stored fact of an issuer's latest 10-K and 10-Q is compared with the value that filing's accession reports. Balance identities are checked where reported. Results appear on a reconciliation page.

**Acceptance**
- [ ] Every stored fact of each issuer's latest 10-K equals the value in that filing (accession-level check): 0 mismatches, or each mismatch explained by a later restatement.
- [ ] FCF, total debt and net debt exist for every year where all inputs exist, and never otherwise.
- [ ] AAPL per-share history is continuous across the August 2020 4-for-1 split, with the reported values still visible.
- [ ] Quarterly values derived from year-to-date filings add up to the annual totals.

## M1.2 Market inputs for valuation
**Build**
- **Market cap and EV, point in time:**
  - market cap = close × period-end shares outstanding;
  - EV = market cap + total debt − cash.
  - Inputs are the close known at T and the latest filing known at T.
- **Multiples:** P/E (TTM diluted EPS), EV/EBITDA, EV/Sales, P/B, FCF yield and earnings yield. Each lists its inputs with their as-of times and sources.
- **Price input for valuation:** the end-of-day consolidated (SIP) close only. An intraday IEX quote, a fixture, a demo or a stale price never feeds a valuation (errata E4); the multiple shows `Data unavailable` instead.

**Acceptance**
- [ ] Every multiple shows its inputs, their as-of times and sources.
- [ ] As known on a past date, multiples use only the filings and closes public by then (test).
- [ ] No multiple is computed from an intraday, fixture, demo or stale price (test).

## M1.3 Valuation models and the Research Record
**Build**
- **DCF,** FCF-based. Inputs:
  - base FCF and a growth path;
  - discount rate = risk-free (FRED `DGS10`, known at T) + an equity risk premium assumption;
  - terminal growth;
  - bear, base and bull scenarios.
- **Reverse DCF:** the growth rate the current price implies.
- **Relative valuation:** each multiple against the company's own history (percentile).
- **Output contract** (02 §3, 01 §3). Every valuation shows:
  - method, assumptions, scenario range;
  - current price, implied upside/downside, margin of safety;
  - model date and source as-of.
  - It is labelled "model output, not fact" (02 §32.2).
- **Assumption sets:** per company, edited by Steven and versioned. A change creates a new version; nothing is overwritten.
- **Fundamental Research dashboard** (the Research Record per company): economics, quality, valuation, capital allocation.

**Acceptance**
- [ ] Every fair value shows method, assumptions, scenario range, current price, implied upside/downside, margin of safety, model date and source as-of.
- [ ] Re-running a valuation as known on a past date with the same assumption version reproduces the same output.
- [ ] Changing an assumption creates a new version; the earlier output stays reproducible.

## M1.4 Buyback engine
**Build**
- **Per company and period:**
  - authorization (amount, date, source);
  - actual repurchase ($ and shares);
  - remaining authorization;
  - intensity (repurchase / market cap; repurchase / FCF);
  - net share reduction (shares bought − shares issued; change in diluted shares);
  - SBC offset;
  - FCF funding (repurchase / FCF);
  - debt-funding flag (net debt up while repurchase > FCF).
- **Announcement detection,** rule-based. Sources: 8-K items and the issuer feeds, with phrases such as "share repurchase program" or "repurchase authorization". Example: NVIDIA's 2026-09-28 release "NVIDIA Announces a $150 Billion Share Repurchase Authorization Increase".
- **States v0.1** (errata E7). Each state:
  - is a deterministic, versioned rule (`rule_version`);
  - is stored with its inputs, thresholds and evidence every time it is assigned;
  - has its own glossary entry.

| State | Rule v0.1 (thresholds approved as defaults, P1-9) | Required evidence |
|---|---|---|
| WATCH | A new or increased authorization in the last 365 days, or remaining authorization ≥ 2% of market cap | The announcement (8-K or issuer release) with its date and amount |
| ACTIVE | WATCH, and repurchases in the latest reported quarter ≥ 0.5% of market cap, and diluted shares down ≥ 1% year over year | Repurchase amount from the 10-Q/10-K; share counts from two filings |
| HIGH-CONVICTION CANDIDATE | ACTIVE, and funded by FCF (TTM repurchase ≤ 1.2 × TTM FCF, net debt not up more than 10% YoY), and valuation context (FCF yield ≥ its 5-year median, or price ≥ 15% below the base DCF value) | FCF, net debt, the valuation output and its assumption version |
| TRADE-READY | HIGH-CONVICTION, and market confirmation (close above its 50-day average or positive 1-month return relative to SPY), and a passed risk check. The risk check arrives in Phase 2, so this state is **unreachable in Phase 1** (P1-4) | Risk check id (Phase 2) |

- **Rules that never change with the thresholds:**
  - An announcement alone reaches WATCH at most (E7).
  - No state ever triggers a buy (02 §5).
  - The thresholds are defaults, not validated (OD-7).
- **Buyback Quality Score** (P1-5): the 02 §5 weights over the available components (undervaluation, actual repurchase intensity, FCF quality, balance-sheet strength, historical discipline, net share-count impact), rescaled without the insider component; shown with its components and the label "default weights, unvalidated".
- **Threshold review** (P1-9): a table of the state each universe company reaches under v0.1, with the inputs, for Steven to confirm or tune (a change is a new rule version).
- **Corporate Actions dashboard:** each company's buyback timeline and its state history.

**Acceptance**
- [ ] Each state assignment stores its rule version, inputs, thresholds and evidence; recomputing as known on a past date reproduces it.
- [ ] A real announcement with no executed repurchase never goes beyond WATCH (test).
- [ ] Authorization, actual repurchase and net share reduction are shown separately for every universe company.

## M1.5 Earnings events
**Build**
- **Events:** 8-K Item 2.02 at its acceptance timestamp, matched to the 10-Q/10-K that follows.
- **Actuals:** revenue, EPS, margins and FCF against the prior quarter and the same quarter a year earlier, from SEC facts.
- **Price reaction,** measured relative to SPY:
  - the return from the last close before the event to the first close after it, plus day +1 and +5;
  - volume against the 20-day average.
- **Guidance** (per P1-3): rule-based extraction of explicit numeric guidance from the 8-K exhibit (EX-99.1). Only the extracted sentences (at most 300 characters each) and the link are stored; never the exhibit text, the same rule as news.
- **Consensus:** `Data unavailable` until OD-3.
- **Earnings dashboard:** past events, actuals against prior, guidance, reaction.

**Acceptance**
- [ ] Every event uses its filing acceptance timestamp, not only the calendar date (01 §23).
- [ ] Reaction windows start at the first close after the event timestamp; an after-hours release is tested for no look-ahead.
- [ ] Consensus fields show `Data unavailable` and are never estimated (errata E6).

## M1.6 Paper journal, signals and the Thesis Card
**Build**
- **Signal and TradeDecision records** per 02 §28 and errata E1 (`strategy_id` nullable, `valid_from`, `created_at`, `user_id`). `mode = paper` only; broker fields null (P1-6).
- **Thesis Card** (02 §17):
  - thesis;
  - 3–7 evidence facts, each with its source and time;
  - catalysts, invalidation, the valuation it relies on;
  - an explicit NO TRADE choice.
- **Full trace:** every journal entry records the `(known_at, system_time)` pair (ADR-012), the assumption and rule versions it used, and links to its evidence rows.
- **Strategy Lab dashboard:** the journal. Backtests come in Phase 2.

**Acceptance**
- [ ] Replaying a journal entry as known at its time reproduces the evidence it cited.
- [ ] No code path can send an order: there is no broker client, and `LIVE_TRADING_ENABLED` stays false (test).
- [ ] NO TRADE decisions are recorded like any other decision.

## M1.7 Alerts Center (in-app)
**Build**
- **Convergence levels L0–L4** (02 §16) as deterministic rules. Inputs are the Phase 1 events: buyback state changes, earnings events, filings. L4 needs the Phase 2 risk check, so it is unreachable in Phase 1.
- **Alerts Center:** in-app, with acknowledgement. Delivery outside the app waits for OD-2.

**Acceptance**
- [ ] Every alert links to the rule version and the evidence that triggered it.
- [ ] Acknowledging an alert is audited.

## M1.8 Phase 1 exit report
Write `docs/reports/phase1_exit.md` in the format of `phase0_exit.md`. Then propose `docs/milestones/M2_*.md` for approval.
