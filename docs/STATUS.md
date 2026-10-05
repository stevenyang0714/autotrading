# STATUS

Update at the end of every session (Claude Code) — newest entry on top of the log.

## Current
- Phase: 0 — Foundation
- Sub-milestone: M0.3 Ingestion framework — LOCAL ACCEPTANCE PASSED; PR + CI pending
- Next: M0.4, starting with `<Metric>` + the Data Health page (pulled forward from M0.9), then the rest of the glossary registry and validation
- Blockers: none
- Open decisions due soon: OD-1 (before M0.7), OD-9 (before M0.7)

## Log
| Date | Sub-milestone | Result | Notes / known gaps |
|---|---|---|---|
| 2026-10-05 | M0.3 | Local acceptance passed. Migration 0002: `ingestion_runs` (one success per idempotency key), `raw_payloads` (append-only, content-addressed), `dead_letters` (audited), source rate-limit columns, `license_status` aligned with the glossary, audit trigger skips no-op updates. Ingestion runner, per-source Redis token bucket, Dramatiq `run_ingestion` with retries and a dead-letter middleware, freshness rules, `config/sources.yaml` (5 Phase 0 sources, all disabled) synced by `make migrate`, read-only API `/data-health`, `/ingestion-runs`, `/dead-letters`. Worker writes its own heartbeat; new `queue` heartbeat. Tests: pytest 74 unit + 44 integration, vitest 25; `make lint` green. Dev DB at 0002; `/health` all ok | QE pass recorded in `docs/reports/qe_2026-10-05.md`; QE findings 1, 3, 4 fixed here, 2 accepted for local use. Data Health page moved to M0.4. Known gaps: no real provider yet (M0.5+); scheduler runs no ingestion schedules until adapters exist |
| 2026-10-05 | M0.2 | Done. PR #2 merged (and PR #3: research watchlists); CI green. Baseline migration 0001: registries seeded and immutable; source registry, entities, instruments, identifiers; `financial_facts` append-only bitemporal; `audit_log` via triggers | ADR-012, errata E14. Known gaps: source withdrawal (tombstone) not modelled |
| 2026-10-05 | M0.1 | Done. PR #1 merged; CI green on the PR and on `main` | Repo moved out of iCloud to `~/Developer/autotrading`. ADR-011 (Silo replaces MinIO), errata E13, dashboard → phase map in ROADMAP |
| 2026-10-04 | Kit created | Specs v2 + errata v2.1 + ADRs + M0 plan | Ready for M0.1 |
