# STATUS

Update at the end of every session (Claude Code) — newest entry on top of the log.

## Current
- Phase: 0 — Foundation
- Sub-milestone: M0.1 Repo scaffold and local stack — LOCAL ACCEPTANCE PASSED; CI run pending (needs the GitHub repo)
- Blockers: none in code. User actions: set git identity, publish the private GitHub repo.
- Open decisions due soon: OD-1 (before M0.7), OD-9 (before M0.7)

## Log
| Date | Sub-milestone | Result | Notes / known gaps |
|---|---|---|---|
| 2026-10-05 | M0.1 | Local acceptance passed. `make up`: all 7 services healthy. `/health`: 200, all 5 components ok (timescaledb 2.30.2 available, bucket exists, worker + scheduler heartbeats fresh). `make test`: pytest 17 unit + 3 integration, vitest 25. `make lint` green. `make migrate` runs (no revisions yet). Redis stopped → `/health` 503 naming redis; recovers on restart. All published ports bound to 127.0.0.1. Web shell checked at desktop and mobile widths: 15 nav entries, no numbers outside "Planned — Phase N" | Repo moved out of iCloud to `~/Developer/autotrading`. ADR-011 (Silo replaces MinIO), errata E13 (dashboard labels in glossary, M0.4), dashboard → phase map in ROADMAP. Fixed during verification: dev-only type stubs were imported at runtime (moved under TYPE_CHECKING); Make 3.81 could not find the per-user Docker CLI (resolved explicitly). Pending: CI run on GitHub |
| 2026-10-04 | Kit created | Specs v2 + errata v2.1 + ADRs + M0 plan | Ready for M0.1 |
