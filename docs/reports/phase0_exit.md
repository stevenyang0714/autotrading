# Phase 0 exit report — Foundation

- **Date:** 2026-10-06 (evidence taken 2026-10-06 11:00 UTC / 19:00 SGT)
- **Scope:** M0.1–M0.9 on `main` at `10abb1e` (Merge PR #13), plus this report (M0.10)
- **Format:** Build Output Contract (02 §31), with the M0.10 additions (acceptance checklist with evidence, open decisions blocking Phase 1)
- **Verdict:** every Phase 0 exit criterion is met (section 8). Phase 1 starts when Steven accepts this report (ROADMAP entry gate) and approves `docs/milestones/M1_fundamentals.md`.

---

## 1. Implementation status

All nine sub-milestones are merged. CI has run 26 times: 25 succeeded and 0 failed. Run #13 was cancelled by a shared concurrency group, which was fixed in M0.5b.

| Milestone | What it delivered | PR | Merge commit | CI (PR / main) |
|---|---|---|---|---|
| M0.1 | Repo scaffold, local stack (Docker Compose), CI, nav with the 15 planned dashboards | #1 | `105f5b2` | #1 / #2 |
| M0.2 | Core schema: canonical registries, Source Registry, identifiers, bitemporal facts (ADR-007, ADR-012), audit log | #2, #3 | `77206de`, `684ad82` | #3 / #4, #5 / #6 |
| M0.3 | Ingestion framework: runs, idempotency, rate limits, raw payloads (SHA-256), dead letters, scheduler | #4, #5 | `f7575ad`, `7f1deb7` | #7 / #8, #9 / #10 |
| M0.4 | Glossary registry, `<Metric>` tooltips, Data Health page | #6 | `582d744` | #11 / #12 |
| M0.5 | SEC EDGAR: tickers, filings index, XBRL company facts with restatements (ADR-013) | #7 | `57ef90a` | #14 / #13 (cancelled) |
| M0.5b | Instrument pages with As known on; XOM predecessor issuer (ADR-014) | #8 | `d04e4bb` | #15 / #16 |
| M0.6 | FRED / ALFRED with vintages (ADR-015); Macro pages; Overview dashboard, Chinese hints, freshness, Build Progress (ADR-016) | #9 | `46ae767` | #17 / #18 |
| Fix | Doubled CHECK constraint names (migration 0007) | #10 | `9ee2624` | #19 / #20 |
| M0.7 | Alpaca prices behind `PriceProvider`, feed status on every price, NYSE calendar (ADR-017) | #11 | `ec2aca0` | #21 / #22 |
| M0.8 | English news: GDELT and nine official feeds, duplicate groups, company mentions (ADR-018) | #12 | `e7f486e` | #23 / #24 |
| M0.9 | Macro series chart with first-release overlay (ECharts), Audit Log page, smoke test of every Phase 0 screen (ADR-019) | #13 | `10abb1e` | #25 / #26 |

Several screens planned for M0.9 were pulled forward with Steven's approval: Data Health (M0.4), Instruments (M0.5b), Macro and Overview (M0.6), prices on instrument pages (M0.7) and News (M0.8).

## 2. Repository / file tree

376 tracked files; about 20,100 lines in `apps/api/src/autotrading` and `apps/web/src`.

```
apps/api/src/autotrading/
  adapters/      sec/ fred/ alpaca/ news/ massive/ (placeholder)
  api/           audit data_health glossary health instruments macro news overview prices progress
  db/            models.py (SQLAlchemy), mixins (provenance, bitemporal)
  domain/        pure rules: facts, fundamentals, indicators, macro, market_calendar, news,
                 prices, provenance, freshness, glossary, metrics, registries, progress
  ingestion/     job, runner, rate_limit, raw_store, schedule, actors
  jobs/          Dramatiq worker, APScheduler scheduler, *_refresh CLIs
  repositories/  insert-only writes (facts, prices, news, audit, identifiers)
apps/api/migrations/versions/   0001–0010
apps/api/tests/                 unit/ integration/ fixtures/{sec,fred,alpaca,news} *_replay.py
apps/web/src/
  app/           / instruments macro news system/{data-health,audit-log,progress} dashboards/[slug]
  components/    Metric, Sparkline, prices/, news/, macro/, audit/, data-health/, overview/, ...
  generated/     api.ts (from openapi.json), glossary.ts (from the glossary seed)
apps/web/e2e/    Playwright (desktop Chrome + Pixel 7)
config/          sources, universe, macro_series, market_calendar, news_{feeds,publishers,entities}, watchlists
docs/            spec, decisions (ADR-001–019), milestones, glossary (+ zh), reports, STATUS.md
infra/           docker-compose.yml (db, redis, objectstore, api, worker, scheduler, web)
```

## 3. Database migrations

The migrations form one linear chain, upgraded and downgraded in tests. `alembic check` passes: models and migrations match.

| Rev | Contents |
|---|---|
| 0001 | Canonical registries (signal families, strategies, source tiers), Source Registry, entities, instruments, identifiers (exclusion constraints), bitemporal `financial_facts`, `audit_log` and triggers |
| 0002 | `ingestion_runs`, `raw_payloads`, `dead_letters`, source rate limits, license values |
| 0003 | `glossary_terms` (immutable versions of complete terms) |
| 0004 | `filings`; `source_concept` on facts; conflicted-row counts |
| 0005 | `entity_relationships` (successor issuers) |
| 0006 | `macro_series`, `macro_observations` (ALFRED vintages) |
| 0007 | Renames 57 doubled CHECK constraint names |
| 0008 | `market_quotes`, `price_bars` (TimescaleDB hypertables) |
| 0009 | `news_items`, `news_mentions` (append-only; title ≤ 500, summary ≤ 300 characters) |
| 0010 | Audit log index (object type, object, id) |

## 4. API contract

FastAPI serves 17 read-only GET routes. The OpenAPI schema is committed as `apps/web/openapi.json`, and the web client types are generated from it; CI fails if they are stale.

- **Health:** `/health/live`, `/health`
- **Operations:** `/data-health`, `/ingestion-runs`, `/dead-letters`, `/audit-log`, `/progress`
- **Glossary:** `/glossary`, `/glossary/{term_id}`
- **Instruments and prices:** `/instruments`, `/instruments/{ticker}/fundamentals`, `/instruments/{ticker}/prices`, `/prices/latest`
- **Macro:** `/macro/series`, `/macro/series/{series_id}/observations`
- **Overview and news:** `/overview`, `/news`

Every data route takes `known_at` (point in time, ADR-012) where it applies. No route writes data. There is no broker, order or account endpoint, and `LIVE_TRADING_ENABLED=false` (ADR-008).

## 5. Provider adapters

| Source | Data | Access / license | Schedule | ADR |
|---|---|---|---|---|
| SEC EDGAR | Tickers, filings index, XBRL company facts (14 metrics) | Public; fair-access User-Agent | Daily 10:00 SGT | 013 |
| FRED / ALFRED | 11 macro series with every vintage | Restricted (FRED terms; ICE/Cboe personal use) | Daily 10:15 SGT | 015 |
| Alpaca Market Data (Basic, paper keys) | IEX snapshots; SIP daily bars since 2016, raw and split-adjusted | Licensed personal; market data host only | Every minute in US hours; bars 06:30 SGT | 004, 017 |
| GDELT DOC 2.0 | News discovery, one query per universe equity | Public; citation and link required | Hourly | 018 |
| Nine RSS / Atom feeds | SEC, Fed, BEA, White House; Apple, NVIDIA, Microsoft, Meta, Google newsrooms | Public; metadata and 300-character summaries only | Every 30 minutes | 018 |
| Massive | — (placeholder behind `PriceProvider`, never configured) | Awaiting license check | — | 004 |

Every adapter:
- reaches only its own host;
- takes rate-limit tokens per source;
- stores the raw payload with its SHA-256;
- writes through the insert-only repositories with full provenance.

Recorded real responses exist for every provider (`apps/api/tests/fixtures/`). CI loads them through the real jobs, labelled `fixture`.

## 6. UI routes and working dashboard

| Route | Shows |
|---|---|
| `/` Overview | Markets block (8 ETFs with feed status, SPY year); six macro blocks with ten rule-based indicators and cited insights |
| `/instruments`, `/instruments/[ticker]` | Prices with feed status and a one-year chart; SEC fundamentals with filing links and restatements; media and company news; As known on |
| `/macro`, `/macro/[series]` | Registry; ECharts series chart with the first release overlaid; observation table with vintages |
| `/news` | Stories with copies collapsed; filters for company, type, source, tier; As known on; GDELT citation |
| `/system/data-health` | Sources, freshness, next refresh, runs, dead letters, audit history links |
| `/system/audit-log` | Every audited change, filters, field-level old → new |
| `/system/progress` | Milestones, phases, open decisions, log (parsed from `docs/` on each request) |
| `/dashboards/[slug]` | The 15 dashboards of 02 §21, each "Planned — Phase N" with no data |

Throughout the UI:
- every number sits in a `<Metric>` tooltip, with a Chinese name and hint on key labels;
- times are shown in SGT with ET alongside;
- desktop and mobile layouts are both covered.

## 7. Tests

Run on the M0.10 branch, 2026-10-06:

| Suite | Result |
|---|---|
| `make lint` (ruff, ruff format, mypy, mypy --strict on `domain/`, eslint, tsc) | Green |
| pytest unit | 220 passed |
| pytest integration (each module on its own migrated database) | 128 passed, 6 skipped (opt-in fixture recorders) |
| vitest | 111 passed (18 files) |
| Playwright (desktop + mobile) | 81 passed, 5 skipped (desktop-only hover or mobile-only tap tests) |
| CI | #25 (PR #13) and #26 (`main` after merge) green: backend, frontend, compose smoke |

The compose smoke job in CI:
1. builds the stack;
2. replays the recorded SEC, FRED, Alpaca and news responses offline with `SCHEDULED_INGESTION=false`;
3. runs the integration and browser tests against it.

Not applicable: the 02 §31 validation report before any execution capability. Phase 0 has no order path.

## 8. Acceptance

### 8.1 Phase 0 exit criteria

Sources, quoted word for word in the table:
- `M0_foundation.md` line 5
- 02 §29
- 01 §29
- errata E5

All evidence queries were run twice, 20 seconds apart, and returned identical results.

| Criterion | Evidence | Result |
|---|---|---|
| **"Real market + SEC + macro + English news"** (02 §29) | Live dev database: 10,666 financial facts, 196,603 filings, 83,715 macro observations, 97,344 daily bars, 18 latest IEX quotes, 207 news items. All 13 enabled sources `fresh` (section 10). Alpaca IEX satisfies "real market data" with `live_single_venue` shown (errata E5). | Met |
| **"No fake live data"** / "nothing fake can look live" / "no mock-live confusion" | Every price carries its feed status (`/prices/latest` now: 18 × `end_of_day`, market closed). Without a key: `unavailable`, no number (`test_without_a_provider_key_no_price_is_shown`). Recorded data is labelled `fixture` and shows the DEMO DATA banner; verified in CI by the e2e tests "DEMO DATA banner appears exactly when recorded prices are shown" and "DEMO DATA banner on news replayed from fixtures". Missing data shows `Data unavailable`. | Met |
| **"Provenance on every observation"** | SQL across the six observation tables: 0 rows missing any provenance field (source, tier, URL, published at, ingested at, as of, license, confidence), and every row links to its raw payload: financial_facts 10,666 / 10,666, filings 196,603 / 196,603, macro_observations 83,715 / 83,715, market_quotes 18 / 18, price_bars 97,344 / 97,344, news_items 207 / 207. NOT NULL and CHECK constraints enforce it (`test_schema.py`). | Met |
| **"Point-in-time queries are reproducible"** | AAPL net income FY2008 as known 2010-01-25: 4,834,000,000; as known 2010-01-27: 6,119,000,000 (10-K/A restatement). PAYEMS Aug 2026 as known 2026-09-30: 159,075 (vintage 2026-09-04); now 159,015 (vintage 2026-10-02, first release 159,075 kept). NVDA as known 2024-06-07 12:00 ET: last close 2024-06-06 1,209.98, 2024-06-03 re-based to 1,150.0000 (pre-split basis). Covered by the integration tests in `test_sec`, `test_macro` and `test_prices`. | Met |
| **"Glossary validation passes in CI"** | 97 complete terms with Chinese hints. `<Metric>` accepts complete terms only (`tsc`). Glossary tests (unit and integration). CI fails if generated files are stale. CI #25 and #26 green. | Met |
| **"Feed status visible everywhere a price appears"** | e2e "every price carries its feed status" on `/`, `/instruments`, `/instruments/AAPL`, desktop and mobile. Instrument price panel, instruments list and Overview tiles render `PriceBadge`. | Met |
| **"Canonical IDs; PIT storage; audit trail"** (01 §29 deliverables) | Canonical families 1–10 and strategies S1–S12 seeded and immutable (`test_registries_match_spec`). Bitemporal facts with append-only triggers. Audit trail of 114 changes, browsable at `/system/audit-log`. | Met |
| **Out of scope respected** ("signals, scores, strategies, backtests, LLM calls, X, Congress PTR, broker code, cloud deployment") | None built. The Overview's indicators and insights are fixed rules on reported data, "not forecasts or advice" (ADR-016); no score or signal is stored. | Met |

### 8.2 Sub-milestone acceptance

Every acceptance box of M0.1–M0.9 is ticked in `docs/milestones/M0_foundation.md`, with the evidence written next to it. Some highlights:

- **M0.5:**
  - 9,948 facts and 192,986 filings at acceptance.
  - Apple FY2008 net income was restated from $4.834B to $6.119B.
  - AAPL FY2025 revenue is $416,161M, linked to accession 0000320193-25-000079.
- **M0.6:** PAYEMS August 2026 was first released at 159,075 and revised to 159,015.
- **M0.7:**
  - With no key, nothing shows a number.
  - The `live_single_venue` badge appears with SGT and ET times.
  - A quote older than its SLA renders `stale`.
- **M0.8:**
  - Every item links to its original article.
  - One real Nvidia buyback headline carried by 33 sites forms one duplicate group.
  - No stored field or payload holds article text.
- **M0.9:** The smoke test and the numbers check cover every Phase 0 screen on desktop and mobile.

Evidence is thinnest for M0.1–M0.4: their boxes carry little or no inline evidence (the M0.4 tooltip box does cite its tests). The test suites above cover them.

## 9. Known gaps

All of these are recorded in ADR-012 to ADR-019 or the STATUS log. They are grouped by the phase that should address them.

**Phase 1 (fundamentals)**
- **Missing derived metrics:** total debt is stored as components and still has to be derived (ADR-013). FCF, net debt, EV and market cap don't exist yet.
- **Restatements vs splits:** split-driven per-share changes are stored as restatements, so per-share history needs explicit split adjustment (ADR-013).
- **Quarterly tables deferred:** 10-Q cash flows are year-to-date.
- **XBRL concepts not mapped yet:** shares outstanding at period end, repurchased shares, authorization amounts, D&A, equity, dividends. Without them, market cap, multiples and buyback analysis can't be computed.
- **Some metrics stay unavailable:** for example JPM gross profit and capex. They are never approximated.
- **Deferred screens (ADR-019):** saved views and export, Macro list sparklines, ETF instrument pages, news paging.
- **`PriceProvider` is narrower than M0.7 planned:** it covers source, live status and configured; it does not yet cover quote, bars, adjusted bars and health. Widen it when Massive is activated (ADR-004).

**Phase 2+**
- **Survivorship-free history** (OD-7): backtests can't report performance until it is decided.
- **Massive (consolidated quotes) not activated:** IEX is one venue with thin volume and wide spreads; prices are always labelled `live_single_venue`.
- **Split ex-dates:** the live IEX day change may span a split on its ex-date. Fixed once corporate actions are stored.
- **No total return:** closes are split-adjusted only.
- **Extended hours** are not covered.

**Phase 3 (news and events)**
- **Event clustering:** one event with different headlines is several stories. For example, NVIDIA's buyback is a press release plus two syndicated headlines.
- **Company matching precision:** 3 of 25 sampled GDELT matches only mention the company. Rule-based for now; language-model linking per ADR-009.
- **Unclassified publishers:** 133 of 139 kept GDELT articles came from unclassified (Tier 4) publishers.
- **GDELT reliability:** it throttles this network hard (HTTP 429 for 30+ minutes) and lagged four days on 2026-10-06. 4 of 10 equities are missing from the news fixtures.

**Data model**
- **No tombstones:** a value a source withdraws is not modelled (ADR-012, ADR-015).
- **ALFRED archive starts:** values published before a series' archive start carry the archive start as their vintage, which is later than the true release (ADR-015).
- **Partial history:** BAMLH0A0HYM2 only from 2023-10-06.
- **Full re-reads:** FRED and SEC re-read the full history daily. There are no conditional requests to SEC.

**Operations** (local deployment, ADR-003; OD-8)
- **Laptop sleep:** scheduled ingestion stops while the laptop sleeps; jobs backfill idempotently on restart.
- **Default credentials:** the database, object store and Redis use default credentials. Acceptable only while every port binds to 127.0.0.1 (QE 2026-10-05, finding 2).
- **Untested:** backup and restore, load testing, non-Chromium browsers.
- **No retention policy** for raw snapshot payloads.
- **Market calendar** ends 2028-12-31.
- **Disk:** the development Mac had 5–8 GB free during M0.8 and M0.9; the Docker build cache was pruned twice.

## 10. Data freshness snapshot

Taken 2026-10-06 11:00 UTC from `/data-health`. `/health`: all six components ok (database, redis, object store, worker, scheduler, queue).

| Source | Freshness | Last success (UTC) | Next refresh (UTC) |
|---|---|---|---|
| sec_edgar | fresh | 10-06 02:00 | 10-07 02:00 |
| fred | fresh | 10-06 02:15 | 10-07 02:15 |
| alpaca_iex | fresh (market closed) | 10-06 05:01 | 10-06 13:30 (next open) |
| gdelt | fresh | 10-06 10:31 | 10-06 11:20 |
| sec_press, fed_press, bea_releases, whitehouse_actions | fresh | 10-06 10:35 | 10-06 11:05 |
| apple_newsroom, nvidia_newsroom, microsoft_news, meta_newsroom, google_blog | fresh | 10-06 10:35 | 10-06 11:05 |
| massive, bls_releases | not enabled | — | — |

Open dead letters: 0. Ingestion runs: 180, of which 179 succeeded.

Newest data by type:

| Data | Newest | Detail |
|---|---|---|
| SEC filing | 2026-10-05 22:42 UTC | |
| Macro vintage | 2026-10-05 | public at the end of the New York day |
| IEX quote | 2026-10-05 20:58 UTC | the last session's close |
| Split-adjusted bar basis | 2026-10-06 04:59 UTC | |
| News item | 2026-10-06 10:00 UTC | |

## 11. Open decisions blocking Phase 1

| ID | Decision | Default until decided | Effect on Phase 1 |
|---|---|---|---|
| **OD-2** | Alert delivery outside the app (email / Telegram / Slack / push) | In-app Alerts Center only | Phase 1 alerts stay in-app |
| **OD-3** | Point-in-time consensus estimates provider | Consensus shown as `Data unavailable` | Earnings work is limited to actual vs prior/YoY, guidance from 8-K text and post-event price reaction (errata E6); S2's consensus part waits |

Needed later:
- OD-4: options data (Phase 5)
- OD-5: short-borrow data (before short ideas)
- OD-6: physical data sources (Phase 3)
- OD-7: survivorship-free data (before Phase 2 backtests)
- OD-8: cloud, auth and backups (Phase 2 exit)
- OD-9: IBKR eligibility (Phase 5)

`docs/milestones/M1_fundamentals.md` lists the questions Steven should answer before Phase 1 starts.

---

**Requested:** Steven's acceptance of this report (the Phase 1 entry gate) and his review of the proposed `M1_fundamentals.md`.
