# Phase 2 — Macro regime, momentum and factors, portfolio risk, walk-forward

**Status:** Approved 2026-10-12 (ADR-029): Steven accepted the Phase 1 exit report, decided P2-1 and chose the OD-7 direction; Phase 2 is in progress (M2.1). Proposed by Claude on 2026-10-12 with the Phase 1 exit report (`docs/reports/phase1_exit.md`). Each sub-milestone still starts in plan mode and is approved before it is built; P2-3 to P2-8 are answered in the plan of the sub-milestone that needs them.

**Goal:** turn the Phase 1 research record into tested, point-in-time context for decisions:
- a deterministic macro regime, reproducible as known on any date;
- versioned price, trend and factor measures for the universe equities and ETFs;
- a paper portfolio with a deterministic risk check that can veto a decision;
- walk-forward backtests with costs in the Strategy Lab, showing their out-of-sample period.

**Phase 2 exit criteria** (ROADMAP, 02 §29):
- "Regime reproducible from PIT data; factor definitions versioned; risk veto deterministic and tested; walk-forward with costs; backtest UI shows OOS period."
- 02 §29: "Regime reproducibility; factor versioning; risk veto deterministic; walk-forward available."

**Entry gate:** Steven accepts the Phase 1 exit report (after M1.7 merges) and decides on Massive (ADR-004, P2-1). **Passed 2026-10-12** (ADR-029).

**Out of scope for Phase 2:**
- **Phase 3:** causal graph, Event Transmission, Policy Monitor, language-model extraction (ADR-009).
- **Phase 4:** X, Congress PTR, Form 4 insiders (and the 5% insider component of the Buyback Quality Score).
- **Phases 5–6:** options, any broker or order path, live trading. The risk check gates paper decisions only.
- **OD-3:** consensus-based surprise and S2.

Work one sub-milestone at a time, in order. Each one ends with the Build Output Contract and a `docs/STATUS.md` update. Every new metric, rule and page ships with its glossary entry and Chinese hint in the same PR.

---

## Decisions for Steven (proposed defaults; each is answered before the sub-milestone that needs it)

| # | Question | Proposed default |
|---|---|---|
| P2-1 | **Massive (ADR-004), the entry gate:** activate consolidated quotes (a paid licensed tier) for Phase 2? | **Decided 2026-10-12: not now** (ADR-029). Regime, factors, risk and backtests run on end-of-day bars, which Alpaca SIP provides; live quotes stay IEX `live_single_venue`. Revisit before Phase 5 (orders) |
| P2-2 | **OD-7: survivorship-free history** (delisted names, index membership) | **Steven compared commercial datasets (`docs/reports/od7_datasets.md`) and decided on 2026-10-13 not to buy for now** (ADR-029, KNOWN_ISSUES KI-1): backtests run on the current universe and do not report performance. Originally proposed: check first whether INSEAD's research data access (e.g. WRDS / CRSP) may be used for personal research; otherwise compare paid datasets (prices to be verified before paying). Until decided: backtests run on the current universe and ETFs and **do not report performance**; the UI says why |
| P2-3 | **Universe for factors** | Keep the 10 equities and 8 ETFs: time-series measures (each instrument against its own history and SPY). Cross-sectional factor ranks wait for OD-7 |
| P2-4 | **Paper portfolio** for the risk cockpit | Notional capital USD 100,000; the open paper TRADEs of the journal are the positions, marked at end-of-day closes |
| P2-5 | **Risk limits (defaults, versioned like the buyback rules)** | Position ≤ 10% of capital; loss at the stated maximum ≤ 1% of capital; one sector ≤ 30%; order size ≤ 1% of the 20-session average volume; a drawdown alert at 10% |
| P2-6 | **Cost model** for backtests | No commission; half the spread plus slippage of 5 basis points per side for the equities, 2 for the ETFs; a sensitivity at double cost |
| P2-7 | **What the risk check unlocks** | TRADE-READY (buyback) and L4 (alerts) become reachable for **paper** decisions once a risk check passes. A paper TRADE records its `risk_check_id` (the Phase 1 database check is relaxed for it only); `mode = paper` and no broker stay enforced |
| P2-8 | **Alert defaults** (ADR-028 A1–A4, built overnight in M1.7) | Confirm, or say what to change (a new alert rule version) |

---

## M2.1 Macro regime engine and Market Regime dashboard
**Decided (ADR-029, R1–R5):** five dimensions and the stress state; six new FRED series (NFCI, NFCICREDIT and STLFSI4 from 2015, VXVCLS, DCOILWTICO, DTWEXBGS); month ends since 2016 backfilled; a stress-state change raises an alert; default thresholds reviewed against the history.

**Build**
- **Regime rules** (`config/regime_rules.yaml` 0.1.0, versioned, sha guard): growth (Sahm rule, payrolls, real GDP), inflation (core PCE against 2% and its direction, CPI), policy and liquidity (real fed funds, NFCI, the 10y–2y inversion), credit (high-yield spread, else the NFCI credit subindex), volatility (VIX and its term structure against VIX 3-month); a growth x inflation quadrant; nine stress flags and the stress state (01 §14: Normal / Elevated / High / Crisis).
- **Point in time:** every classification reads the vintages known at T and the database at S (ALFRED, ADR-012, ADR-015), so a later revision never changes a stored regime.
- **Storage and schedule:** `regime_assessments` (append-only), daily at 10:55 SGT, month ends since 2016 by `make regime-backfill`, `make regime-verify`.
- **Alerts:** alert rules 0.2.0 add market-wide stress alerts to the Alerts Center.
- **Market Regime dashboard:** the regime as known on a date, each dimension with its inputs, vintages and rule; the nine flags; the monthly history of states since 2016.

**Acceptance**
- [x] A regime recomputed as known on a past date equals the stored one, including after a later revision of an input.
- [x] Every regime cites its rule version and the observations (with vintages) behind it.

## M2.2 Price, trend and factor engine
**Build**
- **Definitions** (`config/factor_definitions.yaml`, versioned, sha guard): 12-1 and 6-1 month momentum, 1-month reversal, close against the 50- and 200-day averages, 60-day volatility, return against SPY, and the value and quality measures of the Research Record.
- **Computation** from split-adjusted end-of-day bars and facts known at T, for the 10 equities and 8 ETFs; stored per instrument, date and definition version.
- **Instrument page and dashboard views** of each measure with its inputs.

**Acceptance**
- [ ] Factor definitions are versioned; a changed released definition is refused.
- [ ] Every value recomputes identically as known on its date, across splits.

## M2.3 Portfolio Risk cockpit and deterministic risk veto
**Build**
- **Paper portfolio** (P2-4) from the journal's open TRADEs: positions, weights, exposures by company, sector and factor, beta to SPY, drawdown, liquidity against average volume.
- **Risk check** (P2-5, versioned rules): run on every new paper TRADE and on demand; pass or veto with each limit's value, threshold and evidence; stored append-only and audited.
- **Unlocks** (P2-7): TRADE-READY and L4 for paper decisions when a risk check passes.
- **Portfolio Risk dashboard:** exposures, limits, vetoes, the risk check history.

**Acceptance**
- [ ] The same portfolio, prices and rule version always give the same verdict (tests over every limit and its boundary).
- [ ] A vetoed paper TRADE is refused and the veto is recorded; no path places an order.

## M2.4 ETF rotation research (S3) and the Opportunity Radar
**Build**
- **S3 research:** rule-based rotation across the 8 ETFs from the regime (M2.1) and momentum (M2.2), as signals of family 1 and 5 for strategy S3, paper only.
- **Opportunity Radar** (P1-7): candidates from convergence levels (M1.7), factors and the regime, each with its evidence and the strategy it fits; long only (no short data, OD-5).

**Acceptance**
- [ ] Every candidate and rotation signal cites its rule versions and inputs as known at its date.

## M2.5 Strategy Lab: walk-forward backtests with costs
**Build**
- **Backtest engine** (02 §23) on stored point-in-time data only: signals as they would have been generated at each date, rebalancing on closes, the cost model (P2-6), walk-forward folds with the out-of-sample period marked.
- **Strategies:** S1 (buyback states and score), S3 (ETF rotation), S4 (medium-term momentum), each with its rule versions.
- **Reporting gate (OD-7):** without survivorship-free data, results show the method, trades and costs but not performance figures, with the reason.
- **Strategy Lab:** backtest runs next to the paper journal; runs are stored and reproducible.

**Acceptance**
- [ ] A backtest uses only data known at each simulated date (look-ahead tests: a later restatement, revision or close does not change a stored run).
- [ ] Costs are applied and the out-of-sample period is shown; performance is reported only when OD-7 allows.

## M2.6 Phase 2 exit report
Write `docs/reports/phase2_exit.md` in the format of `phase1_exit.md`. Then propose `docs/milestones/M3_*.md` for approval.
