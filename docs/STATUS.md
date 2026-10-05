# STATUS

Update at the end of every session (Claude Code) — newest entry on top of the log.

## Current
- Phase: 0 — Foundation
- Sub-milestone: M0.2 Core schema, canonical registries, bitemporal facts — LOCAL ACCEPTANCE PASSED; PR + CI pending
- Next: M0.3 Ingestion framework (loads `config/sources.yaml` into `sources`, adds `ingestion_runs` and links facts via `ingestion_run_id` / `raw_payload_sha256`)
- Blockers: none
- Open decisions due soon: OD-1 (before M0.7), OD-9 (before M0.7)

## Log
| Date | Sub-milestone | Result | Notes / known gaps |
|---|---|---|---|
| 2026-10-05 | M0.2 | Local acceptance passed. Baseline migration 0001: registries (families 1–10, S1–S12, tiers 1–4) seeded and immutable; `sources`, `entities`, `instruments`, `identifiers` (exclusion constraints on validity periods, per namespace); `financial_facts` append-only bitemporal; `audit_log` via triggers. Tests: pytest 51 unit + 34 integration (migration up/down/up on an empty DB, `alembic check` clean, registry immutability, fact UPDATE/DELETE/TRUNCATE refused, restatement vs `known_at`, own correction vs `system_time`, date-only publication, provenance NOT NULL, identifier overlap, audit). `make lint` green. Dev DB migrated to 0001; `/health` all ok | ADR-012 (knowledge time = `published_at`; system time from DB clock; date-only → end of NY day), errata E14 (§18 wording; fact timestamps). CI: runner pinned to ubuntu-24.04, uv cache glob fixed. Known gaps: source withdrawal (tombstone) not modelled; sources table empty until M0.3; no UI change |
| 2026-10-05 | M0.1 | Done. PR #1 merged; CI green on the PR and on `main`. `make up`: 7 services healthy; `/health` all ok; `make test` and `make lint` green; Redis-down → 503; ports on 127.0.0.1; web shell checked at desktop and mobile widths | Repo moved out of iCloud to `~/Developer/autotrading`. ADR-011 (Silo replaces MinIO), errata E13 (dashboard labels in glossary, M0.4), dashboard → phase map in ROADMAP |
| 2026-10-04 | Kit created | Specs v2 + errata v2.1 + ADRs + M0 plan | Ready for M0.1 |
