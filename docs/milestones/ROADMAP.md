# ROADMAP — Phases 1–6

Detailed milestone files are written **one phase at a time**, at the end of the previous phase, in the same format as `M0_foundation.md`, and approved by the user before work starts. Do not build ahead of the current phase.

| Phase | Scope (02 §29) | Entry gate | Exit criteria | Blocking open decisions |
|---|---|---|---|---|
| 1 | Fundamental Research Record, valuation (DCF / reverse DCF / multiples with visible assumptions), Buyback engine (authorization vs actual vs net share reduction), Earnings (actual vs prior + guidance + reaction), paper journal | Phase 0 exit report accepted | Financial facts reconcile to filings; buyback states are versioned deterministic rules (errata E7); every fair value shows assumptions and as-of; paper journal records hypothetical decisions with full trace | OD-2, OD-3 |
| 2 | Macro regime engine, momentum/factor engine, Portfolio Risk cockpit, ETF rotation research, Strategy Lab walk-forward | Phase 1 exit; Massive activation decided (ADR-004) | Regime reproducible from PIT data; factor definitions versioned; risk veto deterministic and tested; walk-forward with costs; backtest UI shows OOS period | OD-7 (backtests cannot report performance without it), OD-8 |
| 3 | World / physical / policy: causal graph, Event Transmission dashboard, Policy Monitor with lifecycle states, LLM-assisted extraction (ADR-009) | Phase 2 exit; ADR-009 accepted | Every graph edge has evidence + timestamp; policy lifecycle correct; no execution path from a headline | OD-6 |
| 4 | X researcher watchlists (official API, budget circuit breaker), thesis-change detection, Congress PTR ingestion and lag analytics, Corporate Insider (Form 4) | Phase 3 exit | Provenance on every post/PTR; "Reported Trade" + Disclosure Lag visible; X never a sole trigger | — |
| 5 | Options analytics and hedges, order preview, IBKR paper adapter (Alpaca paper as secondary), reconciliation, kill switch | Phase 4 exit; options data decided | Liquidity and max-loss checks; duplicate-order protection and idempotent orders; paper/live isolation proven; kill switch tested | OD-4, OD-9 |
| 6 | Selective auto-execution for validated sleeves only (S1–S4 candidates) | Phase 5 exit; validation report per strategy (02 §31) approved by user | OOS + walk-forward + costs + robustness + canary + rollback + 100% audit trace | — |

## Standing rules across phases
- Signals and strategies always reference canonical IDs (families 1–10, strategies S1–S12).
- Every new metric ships with its glossary entry in the same PR.
- Every phase ends with `docs/reports/phaseN_exit.md` and a STATUS.md update.
- Execution capability is never enabled as a side effect of another feature.
