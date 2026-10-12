# Phase 1 exit report — Fundamentals, buybacks, earnings, paper journal

- **Date:** 2026-10-12 (evidence taken 2026-10-12 03:00–03:20 UTC / 11:00–11:20 SGT)
- **Scope:** M1.1–M1.6 on `main` at `a4c5f56` (Merge PR #23), M1.7 on `feat/m1.7-alerts` (PR pending), plus this report (M1.8)
- **Format:** Build Output Contract (02 §31), as `phase0_exit.md`: implementation status, files, migrations, API, adapters, UI, tests, acceptance with evidence, known gaps, data freshness, open decisions
- **Verdict:** every Phase 1 exit criterion is met (section 8), on the condition that M1.7 merges with green CI. M1.7's four rule decisions (ADR-028 A1–A4) are Claude's defaults from the overnight build and await Steven's confirmation; changing them is a new alert rule version and does not affect the exit criteria. Phase 2 starts when Steven accepts this report, decides the Phase 2 entry gate (Massive, ADR-004) and approves `docs/milestones/M2_regime_risk.md`.

---

## 1. Implementation status

Phase 1 ran from 2026-10-06 to 2026-10-12. Every sub-milestone started in plan mode with Steven's decisions (ADR-021 to ADR-027), except M1.7, which Steven asked to be built overnight without stopping (ADR-028, proposed). CI ran 20 times in Phase 1 (#29–#48): all succeeded.

| Milestone | What it delivered | PR | Merge commit | CI (PR / main) |
|---|---|---|---|---|
| Fix | SEC acceptance times from filing headers (ADR-013 amendment) | #15 | `d0f1f80` | #30 / #31 |
| M1.1 | 11 new XBRL metrics, filing XBRL reader, class sums, splits (migration 0012), derived values and quarters, filing reconciliation (0013), Reconciliation page (ADR-021) | #16 | `50b79b3` | #32 / #33 |
| M1.2 | Valuation price (last end-of-day close), market cap, EV, TTM EPS, six multiples, Valuation block (ADR-022) | #17 | `1dbfeb5` | #34 / #35 |
| M1.3a | DCF, reverse DCF, relative valuation, assumption versions (0014), the first write endpoint (ADR-023) | #18 | `a284213` | #36 / #37, #38 |
| M1.3b | Research Record, Fundamental Research dashboard (the first live dashboard) (ADR-024) | #19 | `39eb707` | #39 / #40 |
| M1.4a | 8-K buyback statements (0015), authorization vs actual repurchase vs net share reduction (ADR-025) | #20 | `3598652` | #41 / #42 |
| M1.4b | Buyback rule sets and state assignments (0016), Buyback Quality Score, Corporate Actions dashboard; rule 0.2.0 after Steven's review (ADR-025) | #21 | `c48cd55` | #43 / #44 |
| M1.5 | Earnings events at acceptance time, actuals, guidance (0017), reaction against SPY, Earnings dashboard (ADR-026) | #22 | `77ad20e` | #45 / #46 |
| M1.6 | Signals, Thesis Cards, paper TRADE / NO TRADE decisions (0018), replay, paper performance, Strategy Lab (ADR-027) | #23 | `a4c5f56` | #47 / #48 |
| M1.7 | Convergence levels L0–L4, alerts, acknowledgement (0019), Alerts Center (ADR-028, proposed) | pending | — | — |

## 2. Repository / file tree

560 tracked files; about 23,600 lines in `apps/api/src/autotrading` and 13,100 in `apps/web/src` (excluding generated files). New in Phase 1:

```
apps/api/src/autotrading/
  adapters/sec/    eight_k (8-K buyback statements), earnings (8-K results releases), filing_xbrl,
                   reconcile, instance, concepts; adapters/alpaca/splits
  api/             valuation fair_value research buybacks buyback_states earnings reconciliation
                   journal signals alerts
  domain/          derived quarters splits reconciliation valuation fair_value research buyback
                   buyback_announcements buyback_states earnings guidance signals journal
                   convergence (all pure; mypy --strict)
  repositories/    signals convergence
  jobs/            buyback_evaluate signals_backfill alerts_backfill
config/            buyback_rules.yaml (0.1.0 retired, 0.2.0 active), alert_rules.yaml (0.1.0),
                   splits.yaml
apps/web/src/
  app/dashboards/  fundamental-research corporate-actions earnings strategy-lab alerts-center
  app/journal/     new, [cardId]
  components/      instruments/ (valuation, fair value, research, buybacks), buybacks/, earnings/,
                   research/, reconciliation/, journal/, alerts/
```

## 3. Database migrations

One linear chain, upgraded and downgraded in tests; `alembic check` passes. Every Phase 1 table is append-only (update, delete and truncate refused by triggers); the ones holding decisions or rules are audited on insert.

| Rev | Contents |
|---|---|
| 0011 | `ingestion_runs.notes` (corrected acceptance times) |
| 0012 | `split_events` (Alpaca corporate actions since 2016, `config/splits.yaml` before) |
| 0013 | `filing_reconciliations`, `reconciliation_items` |
| 0014 | `valuation_assumptions` (versions, audited) |
| 0015 | `filing_buyback_statements` (sentences ≤ 300 characters, never the document) |
| 0016 | `buyback_rule_sets` (sha guard, audited), `buyback_state_assignments` (TRADE-READY refused) |
| 0017 | `filing_guidance_statements` |
| 0018 | `signals` (paper only), `thesis_cards`, `trade_decisions` (paper mode, no broker, approval state recorded; audited) |
| 0019 | `alert_rule_sets`, `convergence_assessments` (L4 refused), `alerts`, `alert_acknowledgements` (audited) |

## 4. API contract

FastAPI serves 41 paths (43 operations); the OpenAPI schema is committed as `apps/web/openapi.json` and the web types are generated from it (CI fails when stale). Phase 1 added 24 paths:

- **Fundamentals and valuation:** `/instruments/{ticker}/valuation`, `/instruments/{ticker}/fair-value`, `/instruments/{ticker}/assumptions` (GET, POST), `/instruments/{ticker}/research`, `/research`, `/reconciliation`, `/reconciliation/{accession}`
- **Buybacks:** `/instruments/{ticker}/buybacks`, `/buybacks`, `/buybacks/rules`
- **Earnings:** `/instruments/{ticker}/earnings`, `/earnings`
- **Journal and signals:** `/journal` (GET, POST), `/journal/{card_id}`, `/journal/{card_id}/versions` (POST), `/journal/{card_id}/replay`, `/journal/decisions/{id}/exit` (POST), `/signals`, `/instruments/{ticker}/evidence`
- **Alerts:** `/alerts`, `/alerts/{id}`, `/alerts/{id}/acknowledge` (POST), `/alerts/rules`, `/convergence`

Every read takes `known_at` (ADR-012). The five write endpoints (assumptions, journal entry, card version, exit, acknowledgement) write append-only rows as actor `web`, audited, at the database's time; requests with unknown fields are refused. There is no broker, order or account endpoint; `LIVE_TRADING_ENABLED=true` fails start-up (ADR-008).

## 5. Provider adapters

No new provider. New jobs on the existing sources:

| Job | Data | Source | Schedule | ADR |
|---|---|---|---|---|
| `sec.filing_xbrl` | The filing's own XBRL (share classes, cover-page counts) | SEC EDGAR Archives | After each company refresh | 021 |
| `sec.eight_k` | Buyback sentences from 8-K items 2.02 / 7.01 / 8.01 and EX-99 | SEC EDGAR Archives | After each company refresh | 025 |
| `sec.earnings_release` | Guidance sentences from earnings 8-K exhibits | SEC EDGAR Archives | After each company refresh | 026 |
| `alpaca.splits` | Splits since 2016 | Alpaca corporate actions (market data host) | Daily, with the bars | 021 |
| Buyback evaluation | State, score, signal, convergence level and alerts per company | Stored data | Daily 11:00 SGT | 025, 027, 028 |

The SEC client is limited to the endpoints the adapters use; the Alpaca client reaches market-data paths only (`/v2/stocks/`, `/v1/corporate-actions`).

## 6. UI routes and working dashboards

Five of the 15 dashboards are live (all Phase 1 ones on the ROADMAP map):

| Route | Shows |
|---|---|
| `/dashboards/fundamental-research` | Every company's latest period, quality, multiples and DCF; sortable; model output labelled |
| `/dashboards/corporate-actions` | Buyback state per company under the active rules, threshold review, history, timeline |
| `/dashboards/earnings` | Each company's latest release and two years of releases, actuals, guidance, reaction vs SPY |
| `/dashboards/strategy-lab` | Paper journal with returns vs SPY, current signals, new card |
| `/dashboards/alerts-center` | Convergence level per company with every check, alerts with rule version, evidence and acknowledgement |
| `/instruments/[ticker]` | Adds valuation, fair value (with the assumption editor), Research Record, earnings, buybacks, journal |
| `/journal/new`, `/journal/[cardId]` | Write a Thesis Card or a new version; the card with evidence, decisions, exit and replay |
| `/system/reconciliation` | Filing reconciliation results and items |

The other ten dashboards still show "Planned — Phase N" with no data. Every number sits in a `<Metric>` with its glossary term (230 complete terms with Chinese hints); desktop and mobile are covered by the e2e suite.

## 7. Tests

Run on the M1.7 branch, 2026-10-12:

| Suite | Result |
|---|---|
| `make lint` (ruff, ruff format, mypy, mypy --strict on `domain/`, eslint, tsc) | Green |
| pytest unit | 396 passed |
| pytest integration (each module on its own migrated database) | 203 passed, 10 skipped (opt-in fixture recorders) |
| vitest | 199 passed (33 files) |
| Playwright (desktop + mobile, against the local stack) | 133 passed, 11 skipped (CI-only write tests and device-only tests); two timeouts under load passed on rerun |
| CI | Phase 1 runs #29–#48 green (backend, frontend, compose smoke); M1.7 pending |

Write tests (saving assumptions, writing journal cards with exit, acknowledging an alert) run only on CI's throwaway database, because those tables are append-only.

Not applicable: the 02 §31 validation report before any execution capability. Phase 1 has no order path.

## 8. Acceptance

### 8.1 Phase 1 exit criteria

Sources: ROADMAP Phase 1 row and 02 §29 Phase 1, quoted in the table. Evidence queries were run twice, 20 seconds apart, and returned identical results.

| Criterion | Evidence | Result |
|---|---|---|
| **"Financial facts reconcile to filings"** (ROADMAP); **"Filing reconciliation"** (02 §29) | 91 filings reconciled at their acceptance time (each issuer's latest 10-K and 10-Q and those since 2019 with share counts): 90 pass, 1 warn (JPMorgan Q2 2020: 37 of 44 checks matched, 0 mismatched); 0 mismatched, 0 missing, 0 extra facts. Every latest 10-K and 10-Q passes. `/system/reconciliation`; integration tests in `test_reconciliation`. | Met |
| **"Buyback states are versioned deterministic rules (errata E7)"** | `buyback_rule_sets`: 0.1.0 (retired, sha256 `ce338c41…`) and 0.2.0 (active, `7966ec40…`, Steven's review B12–B14); a changed released version is refused by `make migrate` and both hashes are pinned in a unit test. 1,420 assignments (710 per version), each with its T, system time, rule and extractor versions and the whole assessment. `make buyback-verify`: 20 of 20 latest recompute identically (and 40 random of each version at M1.4b). E7: an announcement alone never passes WATCH (unit and integration tests; NVIDIA's press release). TRADE-READY refused by the database (P1-4). | Met |
| **"Every fair value shows assumptions and as-of"**; **"valuation assumptions"** (02 §29) | `/instruments/{ticker}/fair-value` for all 10 equities: labelled "Model output, not fact", with the assumption version (the built-in default: no version saved yet) and its parameters, and the data dates (latest filing with link, risk-free observation, valuation close). DCF available for 8 of 10; JPMorgan (bank) and ExxonMobil (no separate SBC line) say why not. Versions are append-only and audited; switching back reproduces the earlier result (CI e2e). | Met |
| **"Authorization vs actual repurchase"** (02 §29) | `/instruments/{ticker}/buybacks` shows announcements (491 statements from 8-Ks, sentences only), actual repurchases and net share reduction as separate blocks for every company; Apple FY2025 $90.7B repurchased, 343.5M fewer shares (M1.4a). | Met |
| **"Paper journal records hypothetical decisions with full trace"**; **"paper journal"** (02 §29) | `thesis_cards` and `trade_decisions` store T and system time, 3–7 evidence rows as snapshots, the valuation with its assumption version, the cited signals (with their rule version) and the decision; append-only and audited as `web`. Replay of the AAPL demo card: 6 of 6 items identical; the integration test replays identically after a correction, a restatement, a revised close and a new buyback state. Database checks keep every decision paper: mode paper, no broker, approval state recorded. 574 signals from qualifying assignments, all paper only. | Met |
| **Out of scope respected** (Phase 2+: regime and factor engines, Portfolio Risk, backtests; ADR-009 language models; Phase 4 sources; broker, orders, live trading; errata E3 mixed scores; OD-3 consensus) | None built. No broker client: the only market host is Alpaca's data host and no source file names a trading endpoint (`test_paper_only`); `LIVE_TRADING_ENABLED=true` refused (`test_settings`). Consensus and surprise always `Data unavailable`. The Buyback Quality Score is positive-direction only. Opportunity Radar stays planned (P1-7). | Met |

### 8.2 Sub-milestone acceptance

Every acceptance box of M1.1–M1.7 is ticked in `docs/milestones/M1_fundamentals.md` with its evidence. Highlights:

- **M1.1:** 91 filings reconciled; total debt for 9 of 10; per-share continuity across the AAPL, NVDA, GOOGL and ORLY splits.
- **M1.2:** market cap on the latest dated share count; NVIDIA $2.97T before and after its 2024 split.
- **M1.3:** a saved assumption version reproduces its result; Apple's reverse DCF growth 23.3%.
- **M1.4:** six companies ACTIVE under rule 0.2.0 (Apple, AutoZone, JPMorgan, NVIDIA, O'Reilly, ExxonMobil); assignments recompute identically after late filings and restatements.
- **M1.5:** 233 earnings releases at their EDGAR acceptance time, 232 matched to their 10-Q/10-K; an after-hours release has no reaction until the next close; consensus never estimated.
- **M1.6:** replay identical after later data; no code path can send an order; NO TRADE recorded like a TRADE.
- **M1.7:** every alert links its rule version and evidence; acknowledgement audited (CI e2e pending the PR run).

## 9. Known gaps

Recorded in ADR-021 to ADR-028 and the STATUS log; grouped by the phase that should address them.

**Phase 2 (regime, factors, risk, backtests)**
- **Validation (OD-7):** buyback thresholds, the Buyback Quality Score weights and the alert rules are defaults, never validated; no backtest can report performance without survivorship-free data.
- **TRADE-READY and L4 unreachable** until a deterministic risk check exists (P1-4).
- **Paper performance:** closes only; no costs, slippage, dividends or fills; a limit price is recorded, not simulated.
- **Price data:** IEX single venue for live quotes; Massive not activated (ADR-004 decision is the Phase 2 entry gate); no total return.

**Fundamentals**
- **Banks and special cases:** JPMorgan has no DCF and lacks most quality measures; ExxonMobil needs an assumption version without SBC; XOM diluted shares unavailable after 2013 (fallback to basic where diluted EPS = basic EPS).
- **Coverage:** cash excludes marketable securities; Microsoft and Alphabet report no D&A; Apple, Microsoft and Alphabet tag no current buyback authorization; AutoZone, NVIDIA and JPMorgan lack a net share count component in some quarters (B5).
- **Single discount rate, no peer set** for relative valuation.

**Earnings**
- **No consensus** (OD-3), so no surprise and no S2 signal; guidance only where the release states numbers (six companies give none); the 8-K time is used even when a press release went out earlier; early closes before 2026 not in the calendar.
- **Open confirmation:** O'Reilly's and Lowe's comparable-sales growth is classified as revenue guidance ("Sales growth").

**Journal and alerts**
- **One user, no sign-in;** the API binds to localhost only.
- **Invalidation is recorded, not monitored;** alerts are in-app only (OD-2).
- **Alert rules 0.1.0 are Claude's defaults** (ADR-028 A1–A4), awaiting Steven's review; families are coarse and earnings count as releases, not by direction.

**Operations**
- **Open dead letters:** 3 — one `sec.company` run from 2026-10-06 before the acceptance-time fix (superseded by later runs) and two GDELT requests throttled with HTTP 429.
- **Local deployment only** (OD-8): laptop sleep pauses ingestion; default credentials behind 127.0.0.1; no backup and restore test.
- **Disk:** the Docker build cache still needs occasional pruning on the development Mac.

## 10. Data freshness snapshot

Taken 2026-10-12 03:17 UTC from `/data-health`. `/health`: all six components ok (database, redis, object store, worker, scheduler, queue).

| Source | Freshness | Last success (UTC) | Next refresh (UTC) |
|---|---|---|---|
| sec_edgar | fresh | 10-12 02:56 | 10-13 02:00 |
| fred | fresh | 10-12 02:56 | 10-13 02:15 |
| alpaca_iex | fresh (market closed, Sunday) | 10-12 00:50 | 10-12 13:30 |
| gdelt | fresh | 10-12 03:04 | 10-12 03:20 |
| sec_press, fed_press, bea_releases, whitehouse_actions | fresh | 10-12 02:55 | 10-12 03:35 |
| apple_newsroom, nvidia_newsroom, microsoft_news, meta_newsroom, google_blog | fresh | 10-12 02:55 | 10-12 03:35 |
| massive, bls_releases | not enabled | — | — |

Ingestion runs: 2,844, of which 2,806 succeeded; of the other 38, 31 were skipped by design, 3 failed, 3 were dead-lettered and 1 was running. Live data: 19,762 financial facts, 196,959 filings, 97,506 daily bars, 262 news items, 491 buyback statements, 357 guidance statements, 7 splits; 0 rows missing provenance in the Phase 1 observation tables (statements and splits). Audit log: 410 changes.

| Data | Newest |
|---|---|
| SEC filing | 2026-10-09 21:30 UTC |
| Daily close | 2026-10-09 (the last session) |
| News item | 2026-10-10 06:45 UTC |
| Buyback assignment, signal, convergence level | 2026-10-12 03:00 UTC (the daily evaluation) |

## 11. Open decisions blocking Phase 2

| ID | Decision | Default until decided | Effect on Phase 2 |
|---|---|---|---|
| **ADR-004 / Massive** | Activate Massive (consolidated quotes, licensed tier) or stay on Alpaca | Alpaca: IEX quotes, SIP end-of-day bars | Entry gate on the ROADMAP. Regime, factors and backtests use end-of-day bars, which Alpaca provides |
| **OD-7** | Survivorship-free history including delisted names | Backtests run but cannot report performance | Blocks walk-forward results and the validation of every Phase 1 default |
| **OD-8** | Cloud, auth, backups | Local only | Needed by the Phase 2 exit |
| **ADR-028** | Confirm or change the alert defaults A1–A4 | Alert rules 0.1.0 | None on the gate; a change is a new rule version |

Needed later: OD-2 (alert delivery), OD-3 (consensus), OD-4 (options, Phase 5), OD-5 (short borrow), OD-6 (physical data, Phase 3), OD-9 (IBKR, Phase 5).

`docs/milestones/M2_regime_risk.md` (proposed) lists the Phase 2 sub-milestones and the questions to answer before it starts.

---

**Requested:** Steven's acceptance of this report (the Phase 2 entry gate, after M1.7 merges), his decision on Massive (ADR-004) and OD-7, and his review of the proposed `M2_regime_risk.md`.
