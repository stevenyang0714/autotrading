# Phase 3 — Policy, events and the world: causal evidence without execution

**Status:** Approved 2026-10-19 (ADR-035): Steven answered P3-1 to P3-6 with the proposed defaults and decided OD-6 (P3-5). Proposed by Claude on 2026-10-18 with the Phase 2 exit report (`docs/reports/phase2_exit.md`). The entry gate is met: the Phase 2 exit (#31) and ADR-009 accepted (ADR-034). Order: M3.0 carry-overs, then policy, the causal graph and the physical data (ADR-034 E4). Each sub-milestone still starts in plan mode; Claude decides its scope and thresholds (ADR-035).

**Goal:** turn official policy actions and news events into cited, time-stamped evidence about who is exposed, without ever trading on a headline:
- a Policy Monitor that follows each US policy action through its lifecycle, from official sources only;
- language-model extraction and linking under a hard budget, every call logged and every field cited (ADR-009);
- news stories clustered into events and linked to the companies they concern;
- an Event Transmission graph from events and policies to goods, sectors, companies and instruments, where every edge has evidence and a timestamp;
- physical data and the Global Monitor once OD-6 is decided.

**Phase 3 exit criteria** (ROADMAP, 02 §29, 01 §29):
- ROADMAP: "Every graph edge has evidence + timestamp; policy lifecycle correct; no execution path from a headline."
- 02 §29: "Causal evidence; policy lifecycle; no event-only execution."
- 01 §29: "causal evidence; policy lifecycle correctness; no direct execution from headline."

**Entry gate:** "Phase 2 exit; ADR-009 accepted" (ROADMAP). Met: ADR-009 accepted on 2026-10-18 (ADR-034), the Phase 2 exit merged on 2026-10-18 (#31).

**Out of scope for Phase 3:**
- **Phase 4:** X, Congress PTR, Form 4 insiders.
- **Phases 5–6:** options, any broker or order path, live trading. S5 (event / supply chain) and S9 (political headlines) stay alert-only; no event or headline makes a TRADE, a TRADE-READY or an L4.
- **OD-3:** consensus estimates and S2.
- **OD-7:** backtest performance stays withheld.
- **Cloud and sign-in:** local only (ADR-034).
- **Language models deciding anything:** they extract, link and summarize; valuation, factors, risk, sizing and eligibility stay deterministic (02 §24).

Work one sub-milestone at a time, in this order (ADR-035): M3.0, M3.0b, M3.0c (added 2026-10-21, ADR-038), M3.7, M3.7b (added 2026-10-26, ADR-040), M3.1, M3.2, M3.8, M3.3, M3.4, M3.9, M3.5, M3.6. Each one ends with the Build Output Contract and a `docs/STATUS.md` update. Every new metric, rule and page ships with its glossary entry and Chinese hint in the same PR.

---

## Decisions (all decided 2026-10-19, ADR-035)

| # | Question | Proposed default |
|---|---|---|
| P3-1 | **Policy sources:** which official sources feed the Policy Monitor? Adding a provider needs Steven's approval. | **Decided 2026-10-19 (ADR-035): as proposed.** The White House actions feed (already ingested) and the **Federal Register API** (free, official, no key): executive orders, proclamations and the notices of USTR, Commerce (BIS export controls) and Treasury. USTR press releases by RSS. OFAC sanctions lists later. |
| P3-2 | **Language-model tasks and evaluation** | **Decided 2026-10-19 (ADR-035): as proposed.** Two tasks only: (1) extract a policy object from an official document (status, effective date, affected goods, sectors, countries and the universe instruments), each field with the sentence it came from; (2) link a news event to universe companies, with the sentence. A small, cheap model by default (from `LLM_MODEL`), a larger one only when the small one is unsure. A labelled evaluation set of about 50 documents and 50 events, released as a version; a prompt or model change is a new version with its evaluation. Target: at least 90% correct status and effective date, and no uncited field. |
| P3-3 | **Policy scope** | **Decided 2026-10-19 (ADR-035): as proposed.** Tariffs, export controls (semiconductors and other critical technology), sanctions and critical minerals. Mapped to the 10 companies and 8 ETFs through a reviewed table of goods and sectors, for example NVDA with export controls, XOM and XLE with energy sanctions, LOW, AZO and ORLY with tariffs on imported goods. |
| P3-4 | **Causal graph edges** | **Decided 2026-10-19 (ADR-035): as proposed.** Node types: event, policy, good or sector, company, instrument. Edge types: triggers, affects, exposes, confirmed by price. Every edge cites a source sentence or a stored row and has a timestamp. Exposure is a range (low, base, high), never one forecast. Price confirmation reads the stored factor snapshots. Edges proposed by rules or extraction are marked as such. |
| P3-5 | **OD-6 physical data** | **Decided 2026-10-19 (ADR-035): as proposed.** NASA FIRMS active fires (free, a key in `.env`) and NOAA's ENSO index (free), for energy and agriculture exposure. Shipping and port data stay out (paid vendors). The Global Monitor shows `Data unavailable` for any layer not decided. |
| P3-6 | **Phase 2 carry-overs before the new features** | **Decided 2026-10-19 (ADR-035): as proposed.** A short **M3.0**: regime rules 0.2.0 (KI-3, KI-4, KI-5, KI-7: credit fallback, the NFCI threshold, VIX alone, the stagflation band) with a backfill and the alerts raised again, and S4's daily assessment with family 5 signals and Radar candidates (KI-21). Risk rules 0.2.0 (KI-13, KI-20) wait for OD-7. |

---

## M3.0 Phase 2 carry-overs
**Decided (ADR-036, D1-D8, Claude under ADR-035):** CRISIS on two of three conditions, the NFCI flag above -0.25, VIX above 30 needs a second flag for HIGH, the quadrant reads the inflation direction; daily regime, rotation and S4 history since 2016/2017; rotation 0.2.0, alert rules 0.5.0, backtest rules 0.2.0.

**Build**
- **Regime rules 0.2.0:** the thresholds Steven reviews against the history since 2016 (KI-3, KI-4, KI-5, KI-7), a backfill under the new version, rotation and alerts recomputed on it.
- **S4 daily:** the momentum assessment stored daily, family 5 signals for S4, S4 candidates on the Opportunity Radar.

**Acceptance**
- [x] Regime rules 0.2.0 recompute identically as known on their dates; 0.1.0 is kept and its rows unchanged.
- [x] S4 signals cite their rule version and factor snapshots, as S3's do.

## M3.0b Telegram alert delivery (OD-2, ADR-035)
**Decided (ADR-037, T1-T10, Claude under ADR-035):** delivery rules 0.1.0 (stress, L3/L4, S3 and S4 targets, drawdown; never backfilled or older than 48 hours; quiet 23:00-07:00 SGT), alert rules 0.6.0 for S4 alerts, a ledger with one sent row per alert, `make telegram-check` run by Steven.

**Build**
- **Delivery:** the platform's own alerts (stress changes, L3 and L4, new S3 and S4 targets, the portfolio drawdown) sent through the Telegram Bot API, with each alert's evidence, its rule versions and the label "rule output, unvalidated, not advice".
- **Settings:** `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` read from `.env` (Steven creates the bot himself); without them nothing is sent, and the Alerts Center says so.
- **Delivery ledger:** every message stored with its alert, its time and Telegram's answer (append-only), with a rate limit and quiet hours.
- **Choice of alerts:** a versioned delivery rule set (which kinds and levels are pushed); backfilled alerts are never pushed.

**Acceptance**
- [x] A new alert is sent once and recorded; a repeat or a backfilled alert is not sent (tested with a fake Telegram).
- [x] No token or chat id appears in logs, the database or the pages.

## M3.0c Chinese pushes with names and reasons, and a weekly digest (ADR-038)
**Why:** Steven tried the M3.0b pushes on 2026-10-21. They did not say which company a ticker is or why a rule moved, and he wants to read them for medium-term holding (3-6 months or more).
**Decided (ADR-038, C1-C6, Claude under ADR-035):** reviewed display names for the 18 instruments; delivery rules 0.2.0 in Chinese with each holding's reasons read at the alert's T and S; "規則訊號（模擬，非建議）" wording; a weekly digest on Monday at 08:00 SGT; names on the pages.

**Build**
- **Names:** `config/instrument_labels.yaml`, English and Chinese, with sectors in Chinese; display only.
- **Messages:** S3 and S4 entries, exits and holdings with their momentum conditions; L3/L4 checks; P/E and FCF yield against the company's own history, DCF margin and buyback state; the rule's review rhythm, the backtest's median holding period, stress and quadrant.
- **Weekly digest:** every Opportunity Radar candidate with one line of reasons, recorded in `digest_deliveries` once a week; `make alerts-digest`.
- **Pages:** `name` and `name_zh` in the API; the Radar, signal cards and the Alerts Center show the names.

**Acceptance**
- [x] An S4 target change names each company, its sector and the reasons it entered or left (tested with a fake Telegram).
- [x] Every number in a message is read from rows known at the alert's T and held at its S (percentiles from the stored month-end snapshots).
- [x] The digest is sent once a week and recorded; a second run in the same week sends nothing.
- [x] No message calls a rule output a buy or sell recommendation (買入建議, 賣出建議), and every message ends with the fixed footer.

## M3.1 Language-model foundation (ADR-009)
**Build**
- **One client:** every call goes through one wrapper reading `ANTHROPIC_API_KEY` and `LLM_MODEL` from the settings; feature code never calls the API directly (tested).
- **Usage ledger:** every call stored with its time, model, purpose, input and output tokens, estimated cost and the object IDs it served; append-only.
- **Budget:** USD 50 a month; alerts at 70%, 90% and 100% in the Alerts Center; at 100% a circuit breaker refuses every call until the next month.
- **Extraction contract:** versioned prompts and JSON schemas; every extracted field carries the sentence it came from; an evaluation harness on the labelled set (P3-2).

**Acceptance**
- [ ] Every call is in the ledger with its cost; at 100% of the budget no call is made (tested with a fake client).
- [ ] An extraction without a cited sentence is rejected; the evaluation result is stored with the prompt version.

## M3.2 Policy Monitor
**Build**
- **Sources** (P3-1): the Federal Register API and the White House actions feed, stored with provenance like every other source.
- **Policy objects:** status, jurisdiction, affected goods, sectors and countries, effective date, implementation status, direct and second-order exposure, linked instruments and evidence URLs (02 §7).
- **Lifecycle:** statement, proposal, signed action, effective, implementation, challenged or modified, expired or replaced. A state changes only on an official document; a statement never counts as effective (01 §6).
- **Policy Monitor dashboard** with As known on, and policy alerts (a new alert rule version).

**Acceptance**
- [ ] The lifecycle is correct on the labelled sample; every state cites its official document and time.
- [ ] A statement or proposal never enters the causal model as an effective policy.

## M3.3 News events and company links
**Build**
- **Events:** syndicated stories clustered into one event (a repost chain is one source; 02 §8), with the earliest time and every outlet.
- **Links:** events linked to universe companies by rules first, then the language model with the cited sentence (deferred in ADR-018).

**Acceptance**
- [ ] A repost chain counts as one source; an event's links cite their text.

## M3.4 Event Transmission graph
**Build**
- **Graph** (P3-4): nodes and edges from policies, events, goods and sectors to companies and instruments, each edge with its evidence and timestamp, as known at T.
- **Exposure ranges and price confirmation** from the stored factor snapshots; the outputs are thesis candidates only.
- **Event Transmission dashboard;** S5 and S9 alerts (alert-only).

**Acceptance**
- [ ] Every edge has evidence and a timestamp; the graph as known on a past date is reproducible.
- [ ] No path leads from an event or headline to a TRADE, a TRADE-READY or an L4 (tested, like the no-order test).

## M3.5 Physical data and the Global Monitor (OD-6)
**Build**
- **Sources** (P3-5): NASA FIRMS and the NOAA ENSO index, with provenance.
- **Global Monitor:** a map of current signals, sources, entities, transmission paths and instruments (02 §21); `Data unavailable` for any layer not decided.

**Acceptance**
- [ ] Every layer cites its source and time; no physical reading reaches a decision without the causal graph.

## M3.7 Taiwan market: prices, valuation and flows (ADR-035)
**Decided (ADR-039, TW1-TW14, Claude under ADR-035; the history question by Steven on 2026-10-22):**
- **Source:** the TWSE OpenAPI only. It serves the latest session only, so Taiwan is collected daily from 2026-10-21.
- **History, institutional flows and foreign ownership:** these wait for TWSE's written consent. The website's dated queries fall under its terms of use, Art. 6. Steven sends the request: `docs/requests/twse_history_consent_zh.md`.
- **No TPEx.** Every universe member is TWSE-listed.
- **Universe:** the top 10 by market cap on 2026-10-21, plus 0050, frozen in `config/universe_tw.yaml`.
- **Research only.**

**Build**
- **Multi-market support:**
  - `domain/markets.py` (US and TW);
  - XTAI instruments in TWD with `twse` identifiers;
  - the Taipei calendar (`config/market_calendar_xtai.yaml`);
  - Taiwan dates in Taipei time: sessions, the end of day, ex-dates.
- **Source:** the `twse_openapi` adapter, limited to six OpenAPI files, three runs a day:
  - STOCK_DAY_ALL closes;
  - the BWIBBU_d P/E, P/B and dividend yield;
  - MI_MARGN margin and short balances (dated by the chain of balances);
  - TWT48U_ALL dividends;
  - the reference price check;
  - `exchange_measures` (migration 0031).
- **Universe:** the ranking recomputed from the recorded files in a unit test.
- **Factors:** definitions 0.2.0 for Taiwan, against 0050 on Taipei dates; S3, S4 and the Radar keep 0.1.0.
- **Pages:**
  - the Taiwan section on `/instruments`;
  - `/instruments/{code}`: close, valuation with percentiles, margin, dividends, factors against 0050, flows "Data unavailable", the open-data attribution.

**Acceptance**
- [x] Every Taiwan value cites its source and its time; As known on reproduces the stored rows (integration tests on the recorded 2026-10-21 files: a close is known from the end of its Taipei day).
- [x] A Taiwan session never borrows a New York close or calendar (Taipei session dates, ex-dates, month ends and stale check; tests at the New York–Taipei boundary).
- [x] The source is used within its licence: the six OpenAPI files only, the attribution on every Taiwan page, nothing scraped.
- [x] History before 2026-10-21, institutional flows and foreign ownership: from FinMind as a tier 2 source (M3.7b, ADR-040); TWSE's own history still waits for its consent (KI-27).

## M3.7b FinMind: Taiwan flows and history (ADR-040)
**Decided (ADR-040, TW15-TW26; the provider and its scope by Steven on 2026-10-26):** FinMind as a tier 2 supplementary source under its free anonymous tier (personal non-commercial, 資料來源：FinMind, no redistribution): the institutional investors and foreign holdings daily with history since 2016, and the Taiwan history before 2026-10-21 (closes, margin, P/E, ex-dividend results). The TWSE OpenAPI stays primary and is never overwritten.

**Build**
- **Source and client:** six datasets, one request every 12.5 seconds, a 35-minute cooldown on a quota error.
- **Jobs:** `finmind.flows` daily at 21:30 SGT; `finmind.history` once (`make finmind-backfill`).
- **Storage:** flows and holdings in `exchange_measures` (migration 0032 adds the `shares` unit); closes in `price_bars` (feed finmind); dividends from the ex-dividend results (TW20).
- **Factors:** definitions 0.3.0 (TW) with history since 2016; the Taiwan backfill on 0050's sessions (TW17).
- **Pages:** the flows block (net buying by group, latest and last 20 sessions; foreign holding and limit) with the FinMind attribution; both sources in the attribution block.

**Acceptance**
- [x] FinMind never overwrites a TWSE row; on the shared session its values equal TWSE's (TW19, tested on 2026-10-21).
- [x] A changed value is a revision public at the fetch day; the earlier value stays known before it (TW18).
- [x] Ex-dividend results reproduce the reference price or are left out (TW20).
- [x] Every FinMind number names its dataset, time, tier and the attribution line.

## M3.10 Portfolio Center I: real holdings, exchange rate and the Today page (ADR-041)
**Decided (ADR-041, H1-H14; Steven on 2026-10-26):** record Steven's real holdings by hand (local only, backed up; no broker connection, no orders): any US listing or TWSE listing plus cash in each currency, valued in USD (DEXTAUS). Kept apart from the paper portfolio and every rule. Then M3.11 (the Taiwan screens, ADR-042), M3.12 (investment policy and rebalancing) and M3.13 (performance).

**Build**
- **Ledger:** `holding_entries` (append-only, audited; buys, sells, cash dividends, deposits, withdrawals, fees; reversals as the only correction) and `holding_snapshots` (daily 11:12 SGT), migration 0033.
- **Valuation 0.1.0:** average cost per account, fees in cash, splits and stock dividends after the trade, marks at the last close known at T, TWD at the last DEXTAUS rate known at T, the 24-hour change net of deposits and withdrawals.
- **Tracked listings:** a listing outside the universe becomes a tracked instrument on its first entry; Alpaca bars and splits runs of their own (US), `extra_codes` in the TWSE run (closes and ex-rights only).
- **Exchange rate:** DEXTAUS joins the FRED series.
- **Pages:** `/holdings` (summary, positions, cash, totals, entry form, entries with Reverse, As known on); `/` Today (holdings, pushes this week, both markets, the radar, data health) above the macro overview.

**Acceptance**
- [x] Entries are append-only and audited as `web`; each kind's fields are checked by the database; a reversal undoes its entry from its system time on (tested).
- [x] The valuation is reproducible: a snapshot recomputes identically at its own T and S (`make holdings-verify`).
- [x] Only the holdings modules read the ledger: no rule, push, radar or research view sees it (unit test).
- [x] Every number on the Holdings and Today pages carries its glossary term (vitest and e2e).

## M3.11 Taiwan screens: every listed company, the movers and a daily research report (ADR-042)
**Decided (ADR-042, SC1-SC16; Steven on 2026-11-04):** the Taiwan screens read every TWSE-listed company; FinMind serves their prices since 2024 and ex-dividend results once and the candidates' flows daily (at most 150 requests a day); the stocks that change the most come first. Investment policy and rebalancing become M3.12, performance M3.13.

**Build**
- **Listed companies:** the company file as observed (`listed_companies`, migration 0034) and every listed company's daily bar, price change, trade value and announced dividends from the TWSE runs.
- **History:** FinMind prices since 2024 and ex-dividend results for every listed company (`make finmind-listed-backfill`); each ex-date's reference price.
- **Engine:** `domain/screens.py` and `config/screen_rules.yaml` 0.1.0: returns across ex-dates, movers, Swing Trend and Range Breakout with watch lists, the coverage gate.
- **Runs:** 08:05 and 10:00 SGT (`screen_runs`); `make screens-evaluate`, `screens-backfill`, `screens-verify`; the candidates' flows at 21:30.
- **Report:** delivery rules 0.3.0, one Telegram report per run (`screen_deliveries`).
- **Page:** `/dashboards/opportunity-radar/taiwan-screens`, a Today card, 20 glossary terms.

**Acceptance**
- [x] A session is judged only with 95% coverage; otherwise it is recorded as not judged with the reason (tested).
- [x] Since screen rules 0.2.0 (2026-11-05) also only when 90% of the companies with a bar have 60 sessions of history (tested; KI-34).
- [x] Since screen rules 0.3.0 (2026-11-05) also only when 95% of the companies listed by the session have a bar of it, so the backfill starts in 2024, not on the research universe's 2016 histories (tested).
- [x] An ex-dividend drop is not read as a fall (tested on recorded ex-dates of 2330, 2881 and 0056).
- [x] A run recomputes identically at its own T and S (`make screens-verify`, tested).
- [x] The report never carries a FinMind number or a link, and is sent once per run, never for a backfill (tested).
- [x] Every number on the page carries its glossary term (vitest and e2e).

## M3.12 Investment policy and rebalancing
Reads the holdings ledger (M3.10): a versioned investment policy (goals, horizon, risk, target weights and bands by asset class, market and position), drift against it and the trades that would restore the targets (arithmetic on Steven's own targets, not advice). Planned in plan mode after M3.11.

## M3.13 Performance
Time-weighted return of the holdings against SPY and 0050, volatility and drawdown, from the snapshots. Planned after M3.12.

## M3.8 Taiwan fundamentals: monthly revenue and quarterly reports
**Build**
- **Monthly revenue** (published by the 10th of the next month): year-on-year and month-on-month change, each at its publication time.
- **Quarterly reports:** EPS, gross margin and ROE, from an official source whose terms allow it (MOPS checked first).
- **Pages:** Taiwan companies on the Fundamental Research dashboard with the same point-in-time rules.

**Acceptance**
- [ ] Monthly revenue is known only from its publication time (tested with a revision).

## M3.9 Taiwan macro and regime
**Build**
- **Taiwan series:**
  - the business indicators light signal (National Development Council);
  - export orders;
  - PMI;
  - the central bank policy rate;
  - TWD against USD;
  - the TAIEX.
  Each series is added only from an official source.
- **A Taiwan market regime under its own rule version**, reviewed against its history, with US semiconductor stress (SOX) as context.

**Acceptance**
- [ ] Every series cites its vintage or publication time; the regime recomputes identically.

## M3.6 Phase 3 exit report
Write `docs/reports/phase3_exit.md` in the format of `phase2_exit.md`. Then propose `docs/milestones/M4_*.md` for approval.
