# ROADMAP — Phases 1–6

Detailed milestone files are written **one phase at a time**, at the end of the previous phase, in the same format as `M0_foundation.md`, and approved by the user before work starts. Do not build ahead of the current phase.

Phase 1: `M1_fundamentals.md` was approved on 2026-10-06 together with the Phase 0 exit report (`docs/reports/phase0_exit.md`); decisions in ADR-020.

Phase 2: `M2_regime_risk.md` was approved on 2026-10-12 together with the Phase 1 exit report (`docs/reports/phase1_exit.md`); entry decisions in ADR-029.

| Phase | Scope (02 §29) | Entry gate | Exit criteria | Blocking open decisions |
|---|---|---|---|---|
| 1 | Fundamental Research Record, valuation (DCF / reverse DCF / multiples with visible assumptions), Buyback engine (authorization vs actual vs net share reduction), Earnings (actual vs prior + guidance + reaction), paper journal | Phase 0 exit report accepted on 2026-10-06 | Financial facts reconcile to filings; buyback states are versioned deterministic rules (errata E7); every fair value shows assumptions and as-of; paper journal records hypothetical decisions with full trace | None for Phase 1 (OD-2, OD-3 decided for Phase 1 in ADR-020) |
| 2 | Macro regime engine, momentum/factor engine, Portfolio Risk cockpit, ETF rotation research, Strategy Lab walk-forward | Phase 1 exit; Massive activation decided (ADR-004) | Regime reproducible from PIT data; factor definitions versioned; risk veto deterministic and tested; walk-forward with costs; backtest UI shows OOS period | OD-7 (backtests cannot report performance without it), OD-8 |
| 3 | World / physical / policy: causal graph, Event Transmission dashboard, Policy Monitor with lifecycle states, LLM-assisted extraction (ADR-009) | Phase 2 exit; ADR-009 accepted | Every graph edge has evidence + timestamp; policy lifecycle correct; no execution path from a headline | OD-6 |
| 4 | X researcher watchlists (official API, budget circuit breaker), thesis-change detection, Congress PTR ingestion and lag analytics, Corporate Insider (Form 4) | Phase 3 exit | Provenance on every post/PTR; "Reported Trade" + Disclosure Lag visible; X never a sole trigger | — |
| 5 | Options analytics and hedges, order preview, IBKR paper adapter (Alpaca paper as secondary), reconciliation, kill switch | Phase 4 exit; options data decided | Liquidity and max-loss checks; duplicate-order protection and idempotent orders; paper/live isolation proven; kill switch tested | OD-4, OD-9 |
| 6 | Selective auto-execution for validated sleeves only (S1–S4 candidates) | Phase 5 exit; validation report per strategy (02 §31) approved by user | OOS + walk-forward + costs + robustness + canary + rollback + 100% audit trace | — |

## Dashboard → phase map (approved with the M0.1 plan, 2026-10-04)
The phase is the first one in which the dashboard shows real content; until then the page shows "Planned — Phase N" and no data. Source of truth in code: `apps/web/src/lib/dashboards.ts`.

| Dashboard (02 §21) | Phase | Note |
|---|---|---|
| Global Monitor | 3 | Not named in the phase table; inferred from the world/physical scope |
| Market Regime | 2 | Live since M2.1 (2026-10-12) |
| Opportunity Radar | 2 | Live since M2.2 (2026-10-13) with the factor table; candidates with M2.4 |
| Fundamental Research | 1 | Live since M1.3b (2026-10-09) |
| Corporate Actions | 1 | Buybacks first; Form 4 insider activity added in Phase 4 |
| Event Transmission | 3 | |
| Earnings | 1 | |
| X / Expert Watch | 4 | |
| Policy Monitor | 3 | |
| Congress Trades | 4 | |
| Options & Vol | 5 | |
| Portfolio Risk | 2 | Live since M2.3 (2026-10-15): the paper book, limits and risk checks; paper only |
| Alerts Center | 1 | In-app only until OD-2 is decided |
| Strategy Lab | 1 | Paper journal in Phase 1; walk-forward in Phase 2 |
| Execution | 5 | |

The Phase 0 screens from M0.9 (Data Health, Instrument, Macro, News feed, Audit log) are not among the 15 dashboards. They go in a separate "System" nav group. All five were delivered by M0.9 (2026-10-06); Phase 0 closes with the M0.10 exit report.

## Standing rules across phases
- Signals and strategies always reference canonical IDs (families 1–10, strategies S1–S12).
- Every new metric ships with its glossary entry in the same PR.
- Every phase ends with `docs/reports/phaseN_exit.md` and a STATUS.md update.
- Execution capability is never enabled as a side effect of another feature.
