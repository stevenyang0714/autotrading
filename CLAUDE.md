# CLAUDE.md — Global Market Intelligence & Semi-Automated Trading Platform

Personal, single-user research + paper-trading platform for Steven (based in Singapore).
Principle: **360-degree intelligence, selective execution. Research broadly. Trade narrowly.**

## Communication
- Talk to the user in **Traditional Chinese**. Code, comments, commit messages, file names and docs in `docs/` stay in **English**.
- The user is a strategy/tech professional, not a full-time engineer. Explain decisions in plain language, show trade-offs, keep status updates short.

## Source of truth (highest wins on conflict)
1. This file
2. `docs/spec/SPEC_ERRATA_v2.1.md` — resolves known conflicts in the v2 specs
3. `docs/decisions/DECISIONS.md` — ADRs and open decisions
4. `docs/spec/02_master_build_prompt_v2.md` — canonical build spec
5. `docs/spec/01_research_report_v2.md` — product rationale and background

Never silently resolve a conflict. If two sources disagree and the errata does not cover it, stop and ask.

## Where we are
- Current phase and milestone: `docs/STATUS.md` (read it at the start of every session; update it at the end).
- Active milestone plan: `docs/milestones/M0_foundation.md`. Later phases: `docs/milestones/ROADMAP.md`.

## Workflow (every milestone)
1. Read `docs/STATUS.md` and the milestone file. Work on **one sub-milestone at a time** (e.g. M0.3), never several.
2. Start in **plan mode**: propose files, migrations, tests, and risks. Wait for the user's approval.
3. Implement with tests first where practical. Run lint, typecheck and the full test suite before claiming done.
4. Finish with the Build Output Contract (02 §31): status, file tree delta, migrations, API changes, tests + results, acceptance results, known gaps, data freshness status.
5. Update `docs/STATUS.md`, then commit with a conventional message (`feat(m0.3): ...`). One sub-milestone per branch/PR.

**Stop and ask the user before:** spending money or provisioning a paid plan; adding/changing an external provider; changing any canonical decision, ID, schema contract or score direction; touching broker or order code before Phase 5; anything that needs a credential that is not already in `.env`.

## Non-negotiables
- **No fabricated data.** Never invent prices, filings, news, posts, positions or backtest numbers. If real data is missing, the UI shows `Data unavailable` or a visible `DEMO DATA` banner. Test fixtures must be recorded real responses stored under `tests/fixtures/` and are never rendered as live.
- **Every observation carries provenance** (02 §4): source_id, source_tier, published_at, ingested_at, effective_at, as_of, license/access status, confidence. No provenance, no insert.
- **Append-only facts, point-in-time queries.** Never UPDATE or DELETE a stored fact; corrections and restatements create a new version. Every fact table must support "as known at time T".
- **Strategy IDs S1–S12 and Signal Families 1–10 are immutable** (02 §2, §18). X Researcher is a source stream, not a strategy.
- **LLMs never decide trades.** LLMs do extraction, linking, synthesis. Valuation, factors, risk, sizing and execution eligibility are deterministic code.
- **Risk Engine can veto; nothing overrides a veto.** No order without strategy eligibility + risk gate + liquidity gate + approval.
- **Score directions:** Risk Score higher = worse. All other scores higher = better. Never average them without explicit, documented normalization.
- **Source Tier:** Tier 1 = strongest, Tier 4 = weakest (lower number = stronger).
- **Wording:** Congress PTR = "Reported Trade" with visible Disclosure Lag, never "position". Political figures are information sources, never investment authorities. No political persuasion.
- **Glossary contract (02 §22):** every UI metric, score, badge, status, risk measure or strategy renders through the `<Metric termId=...>` component backed by the Glossary Registry. Missing entry = build failure. Tooltip text and calculation share `methodology_version`.
- **No unauthorized scraping, no paywalled full text** as a data dependency. Respect provider terms and rate limits (SEC: declared User-Agent from `SEC_USER_AGENT`, stay well under 10 requests/second).

## Secrets and execution safety
- Never read, print, log or commit `.env*` files or secrets (do not `cat` them via Bash either). Use `.env.example` for variable names.
- Never run `docker compose config`, `docker inspect`, or `env` / `printenv` inside a container: they print resolved secrets.
- Paper trading only until Phase 5 exit. `LIVE_TRADING_ENABLED` must stay `false`; code must refuse to start a live broker session unless Phase 6 gates are recorded as passed.
- Paper and live configuration, credentials and database schemas are isolated.

## Engineering baseline (details in DECISIONS.md)
- Backend: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic, `uv`, `ruff`, `mypy`, `pytest`.
- Data: PostgreSQL + TimescaleDB, Redis (cache/queue, never source of truth), S3-compatible object store (Silo locally, ADR-011).
- Jobs: Dramatiq (Redis broker) + APScheduler; idempotent jobs, retries with backoff, dead-letter queue, freshness SLA.
- Frontend: Next.js (App Router) + React + TypeScript strict, Tailwind, TanStack Query, Apache ECharts, `pnpm`, Vitest, Playwright.
- Local-first via Docker Compose. Store all timestamps in UTC (`timestamptz`); display Asia/Singapore plus exchange-local time for market events.

## Commands
Defined in the root `Makefile` (`make help` lists them). Keep this list current:
- `make setup` — install backend (uv) and frontend (pnpm) dependencies on the host
- `make up` / `make down` — start (waits until healthy) / stop the local stack; `make ps`, `make logs SERVICE=api`
- `make test` — full suite: `make test-unit` (pytest + vitest, no stack) and `make test-integration` (needs `make up`; fails, never skips, when the stack is down). Schema tests run in throwaway `autotrading_*_test` databases, never the dev database.
- `make lint` — ruff, ruff format --check, mypy (strict on `domain/`), eslint, tsc
- `make fmt` — auto-format and auto-fix
- `make migrate` — apply Alembic migrations and sync `config/sources.yaml` into the Source Registry, inside the api container (idempotent; run after `make up`)
- New migration: hand-write it in `apps/api/migrations/versions/`, update `db/models.py`, and keep `alembic check` clean (tested). Facts are written only through `repositories/` (ADR-007, ADR-012).
- `make sec-refresh` — queue an SEC EDGAR refresh now (tickers, then filings + XBRL facts per universe equity); the scheduler also runs it daily at 10:00 SGT. Needs `SEC_USER_AGENT` in `.env`. Re-record SEC test fixtures with `cd apps/api && uv run python -m tests.fixtures.sec.record`
- `make sec-replay` — CI only: load the recorded SEC fixtures (AAPL, XOM and its predecessor) into the stack database, offline
- Instrument pages: http://127.0.0.1:3000/instruments (System group); `?known_on=YYYY-MM-DD` shows what was public by the end of that day in SGT
- `make gen` — regenerate `apps/web/openapi.json` and `apps/web/src/generated/` (glossary + API types) after changing the glossary or the API; CI fails if they are stale
- `make e2e` — Playwright browser tests against the running stack (desktop + mobile)
- `make dev-web` — Next.js dev server on http://127.0.0.1:3000
- Glossary: edit `docs/glossary/glossary_seed.yaml`, then `make gen` and `make migrate`. A complete term's content change needs a `methodology_version` bump. UI code renders metrics only through `<Metric termId=...>`. A PostToolUse hook (`.claude/hooks/glossary-check.sh`) regenerates the glossary types and runs `tsc` after edits under `apps/web/src` or to the glossary; a failure is reported back immediately
- Health: `curl http://127.0.0.1:8000/health` (dependencies) and `/health/live` (process only)

## Repo layout
```
apps/api/           FastAPI app, domain, adapters, jobs (one image for api / worker / scheduler)
apps/web/           Next.js dashboard
config/             universe.yaml, source registry seeds
docs/               spec, decisions, milestones, glossary, reports, STATUS.md
infra/              docker-compose
.github/workflows/  CI (GitHub requires this location)
tests/fixtures/     recorded real API responses (never shown as live)
```

Keep this file short. Put detail in `docs/`, not here.
