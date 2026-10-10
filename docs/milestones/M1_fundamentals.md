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
Plan approved 2026-10-06 with decisions D1–D4 (ADR-021).

**Build**
- **New XBRL concepts,** each checked against the ten issuers' real filings before mapping. Concepts are qualified by taxonomy (us-gaap, dei, srt). New metrics:
  - period-end shares outstanding (us-gaap) and cover-page shares (dei);
  - shares repurchased;
  - buyback authorization (srt since 2021) and remaining authorization;
  - D&A, stockholders' equity, dividends paid, interest expense, income tax, pre-tax income.

  Same rule as ADR-013: a metric a company does not report stays unavailable and is never approximated. Shares issued for compensation is not mapped (3 of 10 report it, with different meanings).
- **The filing's own XBRL (D1):** `sec.filing_xbrl` reads each filing's XBRL instance from SEC Archives. It is used for reconciliation and for class sums.
- **Class sums (D2):** when a filing reports share counts per class only (Meta; Alphabet's cover page), the common classes are added, labelled "sum of classes". Only for inline XBRL filings since 2019-06.
- **Derived metrics,** computed at read time from the values known at the As known on date:
  - free cash flow = operating cash flow − capex (both required);
  - total debt = non-current long-term debt (required) + current portion + commercial paper. A short item the balance sheet does not report counts as 0 and is shown as such (D4);
  - net debt = total debt − cash.
- **Splits (D3):** split events come from Alpaca corporate actions (2016 on) and a reviewed list citing the 8-K (AAPL 2014, Google 2014). Per-share history is split-adjusted beside the reported values. This resolves the ADR-013 restatement-vs-split gap.
- **Quarterly and trailing-twelve-month tables:** 10-Q year-to-date values are differenced into quarters, keeping the provenance of both inputs. EPS uses only the reported three-month values.
- **Reconciliation:**
  - Each issuer's latest 10-K and 10-Q is compared, fact by fact, with what we stored as known at the filing's acceptance time.
  - Also checked: the balance identity, quarters against the reported quarter, and split-like restatements.
  - Results are on the Reconciliation page (`/system/reconciliation`).

**Acceptance**
- [x] Every stored fact of each issuer's latest 10-K equals the value in that filing (accession-level check): 0 mismatches, or each mismatch explained by a later restatement. (Live 2026-10-06: all ten issuers' latest 10-K and 10-Q pass, 0 mismatched / missing / extra; later restatements counted separately.)
- [x] FCF, total debt and net debt exist for every year where all inputs exist, and never otherwise. (Integration test over AAPL, XOM, META; live: total debt for 9 of 10, none for JPMorgan.)
- [x] AAPL per-share history is continuous across the August 2020 4-for-1 split, with the reported values still visible. (FY2017 EPS 9.21 reported, 2.3025 adjusted; also NVDA 2021/2024, GOOGL 2022, ORLY 2025.)
- [x] Quarterly values derived from year-to-date filings add up to the annual totals. (Apple FY2025 quarters sum to $416.161B; Q2/Q3 equal the reported three-month values.)

## M1.2 Market inputs for valuation
Plan approved 2026-10-07 with decisions V1–V3 (ADR-022).

**Build**
- **Market cap and EV, point in time:**
  - market cap = close × the latest dated share count known at T, cover page or balance sheet, split-adjusted to the close (V2);
  - EV = market cap + total debt − cash.
  - Inputs are the close known at T and the latest filings known at T.
- **Multiples:**
  - P/E on TTM diluted EPS (fiscal year + this year to date − last year to date, V1);
  - EV/EBITDA (EBITDA = operating income + D&A; unavailable without D&A, V3), EV/Sales, P/B, FCF yield and earnings yield.
  - Each lists its inputs with their as-of times and sources.
- **Price input for valuation:** the end-of-day consolidated (SIP) close only. An intraday IEX quote, a fixture, a demo or a stale price (more than 5 days old) never feeds a valuation (errata E4); the multiple shows `Data unavailable` instead.

**Acceptance**
- [x] Every multiple shows its inputs, their as-of times and sources. (API and the instrument page's Valuation block; integration test over Apple.)
- [x] As known on a past date, multiples use only the filings and closes public by then (test). (Apple as known 2026-04-15: every source accepted by then, close from 2026-04-14 or earlier.)
- [x] No multiple is computed from an intraday, fixture, demo or stale price (test). (Unit and integration tests; e2e in CI, where closes are fixtures.)

## M1.3 Valuation models and the Research Record
Plans approved 2026-10-07 (F1–F4, ADR-023) and 2026-10-09 (R1–R4, ADR-024). Two PRs:
- **M1.3a, fair value (#18, merged):** DCF, reverse DCF, relative valuation, assumption versions, and the instrument page's Fair value block.
- **M1.3b, Research Record and Fundamental Research dashboard:** quality, economics and capital allocation per period; the first live dashboard.

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
- [x] Every fair value shows method, assumptions, scenario range, current price, implied upside/downside, margin of safety, model date and source as-of. (M1.3a: API contract and the Fair value block; integration test over Apple.)
- [x] Re-running a valuation as known on a past date with the same assumption version reproduces the same output. (M1.3a: identical after a later restatement and a later version; integration test.)
- [x] Changing an assumption creates a new version; the earlier output stays reproducible. (M1.3a: POST creates v2 and v1 is unchanged; audited; e2e saves a version and switches back in CI.)

Added for M1.3b (the spec has no dashboard criteria):
- [x] The dashboard lists every universe equity with economics, quality, capital allocation and valuation as known on the chosen date; each row opens that company's Research Record. (Integration: 3 rows in the test database, values equal to /valuation and /fair-value; e2e: sort by ROIC, open AAPL's record.)
- [x] Every Research Record value shows its inputs, their periods and the filings behind them; a missing input is named; a non-positive denominator is n/m with the reason; nothing is approximated. (Apple FY2025 recomputed from the 10-K's facts; XOM and META gaps named; unit tests for every n/m rule.)
- [x] On a past date, only filings, closes and assumption versions public or saved by then are used. (Apple as known 2026-04-15: every source accepted by then; the latest period is Q1 FY2026.)
- [x] The DCF columns are labelled "model output, not fact" and equal the Fair value block for the same date and version. (Integration test.)
- [x] The dashboard responds in ≤ 3 s for ten equities. (Live 2026-10-09: 0.94 s.)

## M1.4 Buyback engine
Plan approved 2026-10-10 with decisions B1–B10 (ADR-025). Two PRs:
- **M1.4a, data: done (PR pending).** Announcements from 8-Ks and press releases, the buyback record (authorization, actual repurchase, net share reduction per period), the instrument page's Buybacks section. Meets the third acceptance box.
- **M1.4b, states:** rule file, states and score, daily evaluation and backfill, Corporate Actions dashboard and threshold review. Next.

The acceptance boxes are ticked when M1.4b is done.

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
