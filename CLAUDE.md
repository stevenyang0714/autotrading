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
- Paper trading only until Phase 5 exit. `LIVE_TRADING_ENABLED` must stay `false`; code must refuse to start a live broker session unless Phase 6 gates are recorded as passed.
- Paper and live configuration, credentials and database schemas are isolated.

## Engineering baseline (details in DECISIONS.md)
- Backend: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic, `uv`, `ruff`, `mypy`, `pytest`.
- Data: PostgreSQL + TimescaleDB, Redis (cache/queue, never source of truth), S3-compatible object store (MinIO locally).
- Jobs: Dramatiq (Redis broker) + APScheduler; idempotent jobs, retries with backoff, dead-letter queue, freshness SLA.
- Frontend: Next.js (App Router) + React + TypeScript strict, Tailwind, TanStack Query, Apache ECharts, `pnpm`, Vitest, Playwright.
- Local-first via Docker Compose. Store all timestamps in UTC (`timestamptz`); display Asia/Singapore plus exchange-local time for market events.

## Commands
Fill in during M0.1 and keep current:
- `make up` / `make down` — start/stop local stack
- `make test` — full test suite (backend + frontend)
- `make lint` — ruff, mypy, eslint, tsc
- `make migrate` — apply Alembic migrations

## Repo layout (target)
```
apps/api/        FastAPI app, domain, adapters, jobs
apps/web/        Next.js dashboard
config/          universe.yaml, source registry seeds
docs/            spec, decisions, milestones, glossary, reports, STATUS.md
infra/           docker-compose, CI
tests/fixtures/  recorded real API responses (never shown as live)
```

Keep this file short. Put detail in `docs/`, not here.
