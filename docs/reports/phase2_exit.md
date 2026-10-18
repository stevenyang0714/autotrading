# Phase 2 exit report — Macro regime, factors, portfolio risk, walk-forward

- **Date:** 2026-10-18. Evidence was taken 2026-10-17 17:59–18:10 UTC (2026-10-18 01:59–02:10 SGT).
- **Scope:** M2.1–M2.5, on `main` at `cb9c86c` (Merge PR #30). This report (M2.6) is on `feat/m2.6-phase2-exit`, together with the local backups (ADR-034) and the proposed `docs/milestones/M3_world_policy.md`.
- **Format:** the Build Output Contract (02 §31), as in `phase1_exit.md`. Sections: implementation status, files, migrations, API, adapters, UI, tests, acceptance with evidence, known gaps, data freshness, open decisions.
- **Verdict:** every Phase 2 exit criterion is met (section 8), including the 01 §29 criterion "factor overlap visible".
  - Steven decided OD-8 on 2026-10-18: local only, with backups.
  - He accepted ADR-009 on 2026-10-18 (its USD 50 cap included), which is the Phase 3 entry gate.
  - Phase 3 starts when Steven accepts this report and approves `docs/milestones/M3_world_policy.md`.

---

## 1. Implementation status

Phase 2 ran from 2026-10-12 to 2026-10-18. Every sub-milestone started in plan mode with Steven's decisions (ADR-029 to ADR-033); the exit decisions are ADR-034.

CI ran 13 times in Phase 2 (#53–#65):
- 10 succeeded;
- 1 was cancelled because a newer run replaced it;
- 2 failed and were fixed before merge: #58 (a stale OpenAPI schema) and #61 (the CI replay stored an unavailable rotation with a JSON null target).

Every PR's last run and every merge to `main` was green.

| Milestone | What it delivered | PR | Merge commit | CI (PR / main) |
|---|---|---|---|---|
| M2.1 | Regime rules 0.1.0 (five dimensions, nine stress flags, stress state), 6 new FRED series (0020), `regime_assessments` (0021), market-wide stress alerts (alert rules 0.2.0), Market Regime dashboard (ADR-029) | #26 | `e0f5ced` | #53 / #54 |
| M2.2 | Cash dividends (0022), factor definitions 0.1.0 and `factor_snapshots` (0023): momentum, averages, volatility, beta, value and quality percentiles; Opportunity Radar factor table; ETF pages (ADR-030) | #27 | `18e8247` | #56 / #57 |
| M2.3 | Risk rules 0.1.0, the paper portfolio, risk checks and the journal veto (0024); TRADE-READY and L4 unlocked through a daily standard check (0025); portfolio drawdown alert; Portfolio Risk dashboard (ADR-031) | #28 | `abcf999` | #59 / #60 |
| M2.4 | S3 ETF rotation rules and assessments (0026); S3 signals; rotation alerts (alert rules 0.4.0); Opportunity Radar candidates; Strategy Lab rotation (ADR-032) | #29 | `1b07acb` | #62 / #63 |
| M2.5 | S4 momentum rules, backtest rules (cost model), the backtest engine and `backtest_runs` (0027); Strategy Lab backtests with factor overlap; performance withheld (ADR-033) | #30 | `cb9c86c` | #64 / #65 |

## 2. Repository / file tree

There are 676 tracked files (560 at the Phase 1 exit). About 32,100 lines are in `apps/api/src/autotrading` (23,600 at the Phase 1 exit) and 17,000 in `apps/web/src`, excluding generated files (13,100). New in Phase 2:

```
apps/api/src/autotrading/
  domain/          regime factors risk rotation momentum backtest (all pure; mypy --strict)
  repositories/    regime factors risk rotation backtest
  api/             regime factors risk rotation candidates backtests
  jobs/            regime_evaluate factors_evaluate risk_evaluate rotation_evaluate
                   backtest_evaluate backup_objects
  adapters/alpaca/ dividends
config/            regime_rules.yaml factor_definitions.yaml risk_rules.yaml rotation_rules.yaml
                   momentum_rules.yaml backtest_rules.yaml (each 0.1.0, sha guard);
                   alert_rules.yaml 0.2.0-0.4.0; buyback_rules.yaml 0.3.0
infra/             backup.sh restore_check.sh table_counts.sql
apps/web/src/
  app/dashboards/  market-regime opportunity-radar portfolio-risk
  components/      regime/ factors/ risk/ rotation/ candidates/ backtests/
```

## 3. Database migrations

There is one linear chain, upgraded and downgraded in tests; `alembic check` passes. Every Phase 2 table is append-only: updates, deletes and truncates are refused by triggers. Rule sets and risk checks are audited on insert.

| Rev | Contents |
|---|---|
| 0020 | `macro_series.observation_start` (NFCI, NFCICREDIT and STLFSI4 are read from 2015) |
| 0021 | `regime_rule_sets` (sha guard, audited), `regime_assessments`; alerts can be market-wide (kind `regime`) |
| 0022 | `dividend_events` (Alpaca cash dividends since 2016) |
| 0023 | `factor_definition_sets`, `factor_snapshots` |
| 0024 | `risk_rule_sets`, `portfolio_snapshots`, `risk_checks` (trade and on-demand checks audited). A TRADE entry needs a passed, matching check (a CHECK and a trigger) |
| 0025 | TRADE-READY in buyback assignments; levels up to L4; alert kind `portfolio` |
| 0026 | `rotation_rule_sets`, `rotation_assessments`; the strategy joins the signals' unique key (NULLS NOT DISTINCT); alert kind `rotation` |
| 0027 | `momentum_rule_sets`, `backtest_rule_sets`, `backtest_runs` (a CHECK keeps `performance_reported` false) |

## 4. API contract

FastAPI serves 57 paths (60 operations). Phase 2 added 16:

- **Regime:** `/regime`, `/regime/rules`
- **Factors:** `/factors`, `/factors/definitions`, `/instruments/{ticker}/factors`
- **Risk:** `/portfolio`, `/risk/rules`, `/risk/checks` (GET, POST), `/risk/checks/{id}`
- **Rotation and candidates:** `/rotation`, `/rotation/rules`, `/candidates`
- **Backtests:** `/backtests`, `/backtests/{id}`, `/backtests/rules`, `/momentum/rules`

Every read takes `known_at` (ADR-012).

The only new write endpoint is `POST /risk/checks`: it stores a tried trade's risk check, audited as `web`, and never creates a journal entry. `POST /journal` now runs the risk check and refuses a vetoed TRADE.

There is still no broker, order or account endpoint. The no-order test pins every POST path, and checks that rotation, candidates and backtests are read-only. `LIVE_TRADING_ENABLED=true` still fails start-up.

## 5. Provider adapters and engines

There is no new provider. New data:

| Job | Data | Source | Schedule | ADR |
|---|---|---|---|---|
| `fred.series` | NFCI, NFCICREDIT, STLFSI4, VXVCLS, DCOILWTICO, DTWEXBGS (with vintages) | FRED / ALFRED | Daily 10:15 SGT | 029 |
| `alpaca.dividends` | Cash dividends since 2016 (gaps checked) | Alpaca corporate actions | Daily, with the bars (06:30 SGT) | 030 |

New engines, all on stored point-in-time data:

| Engine | Schedule (SGT) | Verify |
|---|---|---|
| Regime assessment and stress alert | 10:55 | `make regime-verify` |
| Factor snapshots (18 instruments) | 11:05 | `make factors-verify` |
| Paper portfolio and drawdown alert | 11:10 | `make risk-verify` |
| S3 rotation, signals and alert | 11:15 | `make rotation-verify` |
| Backtests (S1, S3, S4) | checked 11:20, once a month | `make backtest-verify` |

## 6. UI routes and working dashboards

Eight of the 15 dashboards are live (five at the Phase 1 exit). Every Phase 2 dashboard on the ROADMAP map is live:

| Route | Shows |
|---|---|
| `/dashboards/market-regime` | Stress state, five dimensions with inputs and vintages, nine flags, monthly history since 2016 |
| `/dashboards/opportunity-radar` | Candidates (L3/L4 companies for S1, the S3 ETFs; long only, unranked), and every instrument's trend, risk, value and quality against its own history |
| `/dashboards/portfolio-risk` | The paper book (PAPER ONLY), every limit's use, positions, sectors, risk checks, and a form to try a trade |
| `/dashboards/strategy-lab` | Adds the S3 rotation (`#rotation`) and the backtests of S1, S3 and S4 (`#backtests`): method, in-sample and out-of-sample periods, folds, costs, trades, factor overlap; performance withheld |
| `/dashboards/alerts-center` | Adds L4, plus market-wide stress, portfolio and rotation alerts |
| `/instruments/[ticker]` | Adds trend and factors; ETF pages |

Every number sits in a `<Metric>` with its glossary term: 326 complete terms with Chinese hints (230 at the Phase 1 exit). Desktop and mobile are covered by the e2e suite.

## 7. Tests

Run on `feat/m2.6-phase2-exit`, 2026-10-18:

| Suite | Result |
|---|---|
| `make lint` (ruff, ruff format, mypy, mypy --strict on `domain/`, eslint, tsc) | Green |
| pytest unit | 477 passed (396 at the Phase 1 exit) |
| pytest integration (each module on its own migrated database) | 244 passed, 15 skipped (the web fixture recorders, which run with `RECORD_WEB_FIXTURES=1`) in 9 min 21 s (203 passed at the Phase 1 exit) |
| vitest | 236 passed in 41 files (199 in 33 at the Phase 1 exit) |
| Playwright (desktop + mobile, against the local stack) | 158 passed, 11 skipped (CI-only write tests and device-only tests), 3 failed under load in 4 min 54 s: the page sweep timed out (60 s) on desktop and mobile while loading Fundamental Research, and the PAYEMS "Today" link did not navigate within 5 s. All four reran green on their own (the sweep takes 33 s alone); CI retries once. (133 passed at the Phase 1 exit) |
| CI | Phase 2 runs #53–#65: every PR's last run and every merge green (section 1) |

The write tests (journal TRADE veto, tried trades, acknowledgements) run only on CI's throwaway database, because those tables are append-only.

The 02 §31 validation report before any execution capability is not applicable: Phase 2 has no order path.

## 8. Acceptance

### 8.1 Phase 2 exit criteria

The criteria come from the ROADMAP Phase 2 row, 02 §29 and 01 §29, quoted in the table. Every `*-verify` target was run twice, a minute apart (18:00 and 18:01 UTC), and every stored row recomputed identically both times.

| Criterion | Evidence | Result |
|---|---|---|
| **"Regime reproducible from PIT data"** (ROADMAP); **"Regime reproducibility"** (02 §29) | 135 regime assessments: month ends since 2016, plus daily since 2026-10-13. Each stores its rule version and every input with its vintage. `make regime-verify`: 20 of 20 identical, twice. An integration test shows that a later FRED revision leaves a stored regime unchanged. | Met |
| **"factor definitions versioned"**; **"factor versioning"** (02 §29) | `factor_definition_sets` 0.1.0 has a sha guard, and its hash is pinned in a unit test; a changed released set is refused (integration test). 49,536 snapshots. `make factors-verify`: 314 and 315 identical (the latest 20, 200 random, and those around every split since 2016). | Met |
| **"risk veto deterministic and tested"** (ROADMAP); **"risk veto deterministic"** (02 §29); **"deterministic risk veto"** (01 §29) | Every limit of risk rules 0.1.0 is tested at its boundary (unit). A vetoed TRADE is refused with 422 and the veto stored. The database refuses a TRADE without a passed, matching check. 720 risk checks stored; `make risk-verify`: 120 and 114 identical. | Met |
| **"walk-forward with costs"** (ROADMAP); **"walk-forward available"** (02 §29); **"walk-forward backtest"** (01 §29) | Backtests of S1, S3 and S4 on stored point-in-time data, filled at the next session close, with yearly folds, a base and a double cost scenario (7 and 3 bps per side), turnover, holding periods and exposure. `make backtest-verify`: 3 of 3 identical, twice. Look-ahead integration tests show that a later close revision, regime assessment or factor snapshot never changes a stored run. Performance is withheld (OD-7). | Met |
| **"backtest UI shows OOS period"** (ROADMAP) | Strategy Lab `#backtests` shows the in-sample period up to each rule's release and the out-of-sample period after it (S1: 1 session so far; S3, S4: none yet), and marks each yearly fold. Covered by vitest and by e2e on desktop and mobile. | Met |
| **"factor overlap visible"** (01 §29) | Strategy Lab shows S4's companies also held by S1 (50.78% on average over 66 months) and each strategy's average sectors and beta (S1 0.871, S3 0.759, S4 1.124), served by `GET /backtests`. | Met |
| **Out of scope respected:** Phase 3 (causal graph, Event Transmission, Policy Monitor, language models, ADR-009); Phase 4 sources; options; broker, orders and live trading; OD-3 consensus | None built. No language-model call exists. The no-order test pins the write paths. `LIVE_TRADING_ENABLED=true` is refused. Consensus is always `Data unavailable`. Backtest performance is withheld. | Met |

### 8.2 Sub-milestone acceptance

Every acceptance box of M2.1–M2.5 is ticked in `docs/milestones/M2_regime_risk.md`. Highlights:

- **M2.1:**
  - The stress state at month ends since 2016: NORMAL 110, ELEVATED 15, HIGH 9.
  - The end of March 2020 reads HIGH, not CRISIS (KI-3).
  - Stress-change alerts are raised again under each new alert version (ADR-034's `alerts-backfill`).
- **M2.2:**
  - 747 dividends and two ETF splits that had been missing.
  - NVDA's measures are continuous across its 2024 split.
  - Percentiles are taken only against each instrument's own history.
- **M2.3:**
  - 700 standard checks, all passing (KI-13).
  - TRADE-READY 42 and L4 75 in the backfill, the first being ORLY and AZO in 2021.
  - Tried trades veto as expected (position, sector, maximum loss).
- **M2.4:**
  - 117 month-end S3 targets with 70 changes.
  - October 2026: SPY, QQQ, XLK and XLE at 25% each.
  - 1,038 S3 signals.
- **M2.5:** S1 69 targets, S3 118, S4 117. Costs of 20.6, 17.0 and 34.5 bps a year. Most targets would break the 10% position limit (KI-20).

## 9. Known gaps

These are recorded in ADR-029 to ADR-034 and `docs/KNOWN_ISSUES.md` (KI-1 to KI-22, all open), grouped by what would address them.

**Validation and data (OD-7)**
- No delisted companies (KI-1).
- No threshold is validated (KI-2).
- The ETFs were chosen today (KI-16).
- The out-of-sample periods have barely started, and there are no ablations (KI-22).
- So backtests withhold performance.

**Regime rules 0.2.0 candidates**
- CRISIS is unreachable before 2023-10 (KI-3).
- A dead NFCI flag (KI-4).
- VIX above 30 alone gives HIGH (KI-5).
- Month ends miss spikes (KI-6).
- The quadrant reads stagflation most of the time (KI-7).
- Late inputs (KI-8).
- The As known on day boundary (KI-9).
- No defensive switch in the month-end history (KI-17).

**Factors and dividends**
- Alpaca dividend gaps (KI-10).
- The gap check over-flags (KI-11).
- Six local Decembers have price measures only (KI-12).

**Risk and strategies**
- The standard check almost always passes (KI-13).
- Broad ETFs are not split by sector (KI-14).
- No VaR, ES or stress tests (KI-15).
- Backtest costs are fixed assumptions (KI-19).
- ETF journal entries and limits are deferred (KI-20).
- S4 has no live signal (KI-21).

**Local notes**
- Older rotation alerts list the previous target alphabetically (KI-18).
- The buyback history starts in 2021.

**Operations**
- Local only (OD-8, ADR-034). Laptop sleep pauses the scheduled jobs.
- Backups are manual (`make db-backup`), without encryption or an off-machine copy; that is Steven's choice of destination.
- Default credentials sit behind 127.0.0.1.
- 8 open dead letters: 7 GDELT requests throttled with HTTP 429 and the `sec.company` run from 2026-10-06 (superseded).

## 10. Data freshness snapshot and backup

Taken 2026-10-17 18:04 UTC from `/data-health`. `/health`: all six components ok (database, redis, object store, worker, scheduler, queue).

| Source | Freshness | Last success (UTC) | Next refresh (UTC) |
|---|---|---|---|
| sec_edgar | fresh | 10-17 03:28 | 10-18 02:00 |
| fred | fresh | 10-17 03:16 | 10-18 02:15 |
| alpaca_iex | fresh (market closed, Saturday) | 10-17 01:03 | 10-19 13:30 |
| gdelt | fresh | 10-17 17:27 | 10-17 18:20 |
| sec_press, fed_press, bea_releases, whitehouse_actions | fresh | 10-17 17:35 | 10-17 18:05 |
| apple_newsroom, nvidia_newsroom, microsoft_news, meta_newsroom, google_blog | fresh | 10-17 17:35 | 10-17 18:05 |
| massive, bls_releases | not enabled | — | — |

- **Ingestion runs:** 5,545 in all; 5,482 succeeded, 51 were skipped by design, 3 failed, 8 were dead-lettered and 1 was running.
- **Data:** 19,762 financial facts, 197,386 filings, 97,686 daily bars, 503,456 macro observations, 866 news items, 747 dividends, 9 splits.
- **Engine output:** 135 regime assessments, 49,536 factor snapshots, 2,170 buyback assignments, 720 risk checks, 75 portfolio snapshots, 121 rotation assessments, 3 backtest runs, 1,984 signals, 2,880 convergence assessments, 1,201 alerts.
- **Audit log:** 1,401 changes.

| Data | Newest |
|---|---|
| SEC filing | 2026-10-16 21:23 UTC |
| Daily close | 2026-10-16 (the last session) |
| News item | 2026-10-17 16:15 UTC |
| Regime, factor snapshots, buyback assignments, portfolio, rotation | 2026-10-17 03:14–03:16 UTC (the daily run) |
| Backtest runs | 2026-10-17 15:21 UTC |

**Backup (ADR-034):**
- `make db-backup` at 2026-10-17 17:59 UTC took 1 min 44 s. It wrote a database dump of 80.5 MB and an object archive of 98.0 MB (6,075 raw payloads, 1.52 GB uncompressed) to `~/autotrading-backups/20261017T175910Z`.
- `make db-restore-check` took 42 s. All 50 tables had identical row counts, the alembic version was 0027, and the archive held the 6,075 objects of the manifest. The throwaway database was dropped.

## 11. Open decisions for Phase 3

| ID | Decision | Default until decided | Effect on Phase 3 |
|---|---|---|---|
| **M3 proposal** | Approve `docs/milestones/M3_world_policy.md` and answer P3-1 to P3-6 (policy sources, language-model tasks and evaluation, policy scope, causal graph edges, OD-6 candidates, Phase 2 carry-overs) | Nothing built | Phase 3 starts on approval |
| **OD-6** | Physical data sources (NASA FIRMS, NOAA; shipping vendors) | Not ingested | Needed by M3.5 (Global Monitor) |
| **OD-7** | Survivorship-free history | Backtests withhold performance | Unchanged in Phase 3 |

Decided at this exit (ADR-034):
- **OD-8:** local only, with backups.
- **P2-8:** ADR-028 accepted.
- **ADR-009:** accepted, with the USD 50 cap. This was the Phase 3 entry gate.

Needed later: OD-2 (alert delivery), OD-3 (consensus), OD-4 (options, Phase 5), OD-5 (short borrow), OD-9 (IBKR, Phase 5).

---

**Requested:** Steven's acceptance of this report (the Phase 2 exit), and his review of the proposed `docs/milestones/M3_world_policy.md` with answers to P3-1 to P3-6.
