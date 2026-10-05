# Phase 0 — Foundation (data, schema, glossary, governance)

**Goal:** real SEC + market + macro + English news data flowing into point-in-time, provenance-tracked storage, visible in a minimal dashboard where every metric has a glossary tooltip and nothing fake can look live.

**Phase 0 exit criteria (02 §29 + errata):** no fake live data; provenance on every observation; glossary validation passes in CI; point-in-time queries are reproducible; feed status visible everywhere a price appears.

**Out of scope for Phase 0:** signals, scores, strategies, backtests, LLM calls, X, Congress PTR, broker code, cloud deployment.

Work one sub-milestone at a time, in order. Each one ends with the Build Output Contract and a `docs/STATUS.md` update.

---

## M0.1 Repo scaffold and local stack
**Build**
- Monorepo layout from CLAUDE.md. `infra/docker-compose.yml` with: TimescaleDB (Postgres 16), Redis, S3-compatible object store (Silo, ADR-011), `api` (FastAPI), `worker` (Dramatiq), `scheduler` (APScheduler), `web` (Next.js).
- `Makefile` targets: `up`, `down`, `test`, `lint`, `migrate`, `fmt`.
- Backend skeleton: settings via pydantic-settings reading `.env`; `/health` endpoint reporting DB, Redis, object store status.
- Frontend skeleton: app shell with left nav listing all 15 dashboards (02 §21). Unbuilt dashboards render "Planned — Phase N", never placeholder numbers.
- GitHub Actions CI: ruff, mypy, pytest, eslint, tsc, vitest.
- Fill in the Commands section of CLAUDE.md.

**Acceptance**
- [x] `make up` brings up all services; `/health` returns all green.
- [x] `make test` and `make lint` pass locally and in CI.
- [x] Web shell loads; all 15 nav entries present; no numeric placeholders anywhere.

## M0.2 Core schema, canonical registries, bitemporal facts
**Build**
- Alembic baseline migration. Enable TimescaleDB.
- Registry tables seeded by migration and protected from edits: `signal_families` (1–10, 02 §2), `strategies` (S1–S12 with default mode and unlock conditions, 02 §18/§30), `source_tiers` (1–4).
- `sources` (Source Registry): id, name, url, tier, license/access status, update cadence, freshness SLA, enabled, priority, topics.
- `instruments`, `entities` (issuer/company), identifier map (ticker, CIK, FIGI if available) with validity periods.
- Generic bitemporal pattern per ADR-007; insert-only repository; DB trigger blocking UPDATE/DELETE on fact tables.
- `audit_log` (append-only): actor, action, object type/id, before/after hash, timestamp.

**Acceptance**
- [x] Migrations upgrade and downgrade cleanly on an empty DB.
- [x] Test: attempting to change S1–S12 or family IDs fails.
- [x] Test: UPDATE/DELETE on a fact table is rejected; a correction creates a new version and `as_of()` returns the old value for an earlier `known_at`. Per ADR-012 this holds for source-side corrections (restatements/revisions, new `published_at`); our own corrections are visible at the old value only for an earlier `system_time`. Both are tested.
- [x] Test: inserting an observation without required provenance fields fails validation.

## M0.3 Ingestion framework
**Build**
- Dramatiq actors + APScheduler schedules. `ingestion_runs` table: source, job, params, started/finished, status, row counts, raw payload object keys, error.
- Idempotency key per job (source + params + window). Retry with exponential backoff; after max retries move to dead-letter and record it.
- Redis token-bucket rate limiter configurable per source.
- Raw payloads stored in the object store (Silo, ADR-011) with SHA-256; parsed rows reference the payload.
- Freshness monitor: per source, compare latest successful ingest with its SLA → `fresh` / `stale` / `failing`.

**Acceptance**
- [x] Test: same job run twice inserts no duplicates.
- [x] Test: a job forced to fail lands in dead-letter after N retries and is visible via API.
- [x] Test: freshness flips to `stale` when the SLA is exceeded (time-mocked).

Delivered with M0.3: `config/sources.yaml` synced by `make migrate`; read-only API `GET /data-health`, `/ingestion-runs`, `/dead-letters`. The Data Health page moved to the start of M0.4 (Steven, 2026-10-05).

## M0.4 Glossary Registry and validation (system contract, 02 §22)
**Build**
- **First:** the `<Metric>` component and the **Data Health page** (`/system/data-health`, nav group "System"), built on `GET /data-health`. It shows sources, freshness, last runs, open dead letters and license/access status, all through `<Metric>` with glossary tooltips. Complete the glossary terms it uses (`data_freshness`, `license_status`, `source_tier`, `ingestion_status`, `dead_letter`). Pulled forward from M0.9 (Steven, 2026-10-05).
- Load `docs/glossary/glossary_seed.yaml` into a `glossary_terms` table (versioned) and expose `GET /glossary` and `GET /glossary/{term_id}`.
- Generate a TypeScript union type `GlossaryTermId` from the registry at build time.
- `<Metric termId=... value=... asOf=... feedStatus=...>` component: desktop hover → compact tooltip; mobile tap → help popover. It is the only allowed way to render a metric, score, badge, status, risk measure or strategy label.
- Backend `metric_registry`: every computed metric declares `term_id` and `methodology_version`.
- Validation (CI-blocking):
  1. TypeScript: an unknown `termId` fails `tsc`.
  2. Test: every term used by the UI has `status: complete` (all 17 fields from 02 §22 filled).
  3. Test: every backend metric's `methodology_version` equals its glossary entry's version.
  4. ESLint rule or test: no metric-like component renders outside `<Metric>` (use a `data-metric` attribute convention).
- Complete the seed entries needed by Phase 0 screens (status `seed` → `complete`).
- Per errata E13: add glossary entries for the 15 dashboard labels and the `planned_phase` status label, and render the nav and planned pages through the glossary component.
- Install Playwright and its browsers here, not earlier, to save disk space.
- After the validator exists, add a Claude Code hook in `.claude/settings.json` that runs the glossary check after edits under `apps/web/` (ask the user before changing settings). Done 2026-10-05 with Steven's approval: `.claude/hooks/glossary-check.sh`.

**Acceptance**
- [x] Deliberately adding a metric without a glossary entry fails CI (prove it in the PR, then revert). Proof in PR description; permanently guarded by `@ts-expect-error` cases in `Metric.test.tsx` and the numbers-without-tooltip test.
- [x] Tooltip and popover work on desktop and a mobile viewport (Playwright).

Delivered with M0.4: glossary registry (`glossary_terms`, migration 0003, synced by `make migrate`; `GET /glossary`, `/glossary/{term_id}`), generated `apps/web/src/generated/{glossary,api}.ts` (`make gen`, drift-checked in CI), `<Metric>` with portal tooltips/popovers, the Data Health page (`/system/data-health`), nav and planned pages through the glossary (errata E13), backend metric registry, Playwright e2e in the compose-smoke CI job (`make e2e`).

## M0.5 SEC EDGAR adapter (filings + XBRL facts)
**Build**
- Ticker ↔ CIK map from SEC's company tickers file; store with validity dates.
- Submissions API: filing index per company (form type, accession number, filing date, acceptance datetime, report date).
- Company facts (XBRL): map selected us-gaap concepts to internal `metric_id`s (revenue, gross profit, operating income, net income, EPS diluted, diluted shares, cash, total debt, CFO, capex, share repurchase payments, SBC). Keep the raw concept name for traceability.
- `FinancialFact` per errata E1. A later filing reporting a different value for the same metric/period creates a new version with `restated_flag = true`.
- Requests send `SEC_USER_AGENT`; throttle to ≤ 5 req/s; cache responses.

**Acceptance**
- [x] Facts ingested for every equity in `config/universe.yaml`. Live `make sec-refresh` on 2026-10-05: 11 runs succeeded; 9,948 facts and 192,986 filings for all 10 equities. XOM has only 22 facts, see the ADR-013 known gap.
- [x] Test (recorded real fixture): a restated value produces two versions; `as_of()` before the restatement filing returns the original. Case: Apple FY2008 net income, $4.834bn in the 10-K of 2009-10-27, restated to $6.119bn in the 10-K/A of 2010-01-25 (`tests/integration/test_sec.py`).
- [x] Every fact links to its accession number and filing URL (EDGAR index page). Spot check: AAPL FY2025 revenue of $416,161m matches "Total net sales" in the 10-K, accepted 2025-10-31 06:01:26 ET.

**Notes (M0.5)**
- "Total debt" is stored as three reported components; Phase 1 derives the total (ADR-013).
- Cache: raw responses are content-addressed in the object store; conditional requests are deferred (ADR-013).

## M0.5b Minimal instrument page (pulled forward from M0.9, Steven 2026-10-05)
**Build**
- `/instruments/[ticker]` for the equities in `config/universe.yaml`: key XBRL facts from M0.5 (revenue, net income, diluted EPS, share repurchases, diluted shares, cash, debt) with period, value, unit, filing link and accession number.
- A point-in-time toggle: "as known on date X" uses `as_of(known_at=...)` (ADR-012); restated values show the restatement badge and link the earlier version.
- Every number through `<Metric>`; each XBRL metric gets a complete glossary entry and a backend `METRICS` registration.
- XOM history: link the predecessor issuer Exxon Mobil Corp (ADR-014; added by Steven 2026-10-05).
- No prices, news or valuation yet (M0.7, M0.8, Phase 1).

**Acceptance**
- [x] AAPL page shows real SEC values that match the filing they link to. FY2025 revenue $416.161B links to 10-K 0000320193-25-000079, which reports total net sales of $416,161m (`test_instruments.py`, Playwright).
- [x] Switching "as known on" to a date before a restatement shows the original value. AAPL FY2008 net income is $4.834B as known on 2010-01-25, and $6.119B with the Restated badge on 2010-01-27 (backend, vitest and Playwright).
- [x] No number without a tooltip (unit test + Playwright).
- [x] XOM shows FY2023-2025 from Exxon Mobil Corp (predecessor), labelled, and names it as the issuer before 2026-07-01.

**Notes (M0.5b)**
- "As known on" a date means the end of that day in Singapore time; the page shows the exact SGT and ET timestamp it used.
- Quarterly tables are deferred: 10-Q cash flows are year-to-date and need their own handling (Phase 1).
- CI loads the recorded SEC fixtures (`make sec-replay`), so the instrument e2e tests run on real data without network access.

## M0.6 FRED / ALFRED adapter (macro with vintages)
**Build**
- Series registry seeded with: CPIAUCSL, PCEPILFE, UNRATE, PAYEMS, GDPC1, FEDFUNDS, DGS2, DGS10, T10Y2Y, BAMLH0A0HYM2, VIXCLS (editable).
- Pull observations with real-time periods so each value keeps its vintage.

**Acceptance**
- [ ] Test (recorded real fixture): querying a revised series as known on an earlier date returns the first-release value, not today's revised value.
- [ ] Macro page can toggle "latest" vs "as known on date X".

## M0.7 Market data adapter (PriceProvider)
**Build**
- `PriceProvider` interface: latest quote, daily bars, corporate-action-adjusted bars, health.
- Alpaca Basic adapter first (ADR-004). Massive adapter stub behind the same interface, disabled without key.
- `MarketPriceObservation` per errata E1; `feed_status` per errata E4; staleness SLA per instrument class.
- Daily bars backfilled for the universe; latest quotes on a schedule during US market hours.

**Acceptance**
- [ ] With no API key configured, every price component shows `Data unavailable` (no numbers).
- [ ] With Alpaca configured, prices show the `live_single_venue` badge and as-of time in SGT and ET.
- [ ] Test: a quote older than its SLA renders `stale`.

## M0.8 English news adapter (GDELT + RSS)
**Build**
- GDELT DOC 2.0 queries per universe ticker/company name; configurable official RSS feeds via the Source Registry.
- Store title, source, author, URL, published/updated times, language, short snippet only (no full text).
- Dedup: canonical URL + normalized title similarity → `duplicate_group_id`. Independence counting uses groups, not articles.
- Rule-based entity/ticker extraction using the SEC ticker dictionary (no LLM in Phase 0).

**Acceptance**
- [ ] Every news item links to its original URL.
- [ ] Test: syndicated copies of one story share a `duplicate_group_id`.
- [ ] No stored field contains full article text.

## M0.9 Phase 0 dashboard (first working screens)
**Build**
- **Data Health:** delivered in M0.4 (pulled forward); extend here if Phase 0 sources need more detail.
- **Instrument page:** extend the M0.5b page with price + feed badge and related news groups.
- **Macro page:** series charts with vintage toggle.
- **News feed:** filter by ticker/source/tier; duplicate groups collapsed.
- **Audit log viewer** (read-only).
- All metrics through `<Metric>`; all timestamps SGT + ET where relevant.

**Acceptance**
- [ ] Playwright smoke test across all Phase 0 screens.
- [ ] Glossary validation green; no element shows a number without a tooltip.

## M0.10 Phase 0 exit report
Write `docs/reports/phase0_exit.md` using the Build Output Contract (02 §31): implementation status, file tree, migrations, API routes, provider adapters, UI routes, test results, acceptance checklist with evidence, known gaps, data freshness snapshot, and which open decisions block Phase 1. Then propose `docs/milestones/M1_*.md` in the same format for user approval.
