# Developer commands. Keep CLAUDE.md "Commands" in sync with this file.
# Compatible with the GNU Make 3.81 that ships with macOS.

SHELL := /bin/bash
# Docker Desktop's per-user install puts the CLI in ~/.docker/bin, which is not always on PATH.
# Make 3.81 resolves recipe commands with the original PATH, so resolve the binary explicitly;
# the exported PATH still lets docker find its credential helpers.
export PATH := $(HOME)/.docker/bin:$(PATH)
DOCKER := $(shell command -v docker 2>/dev/null || echo $(HOME)/.docker/bin/docker)
COMPOSE := $(DOCKER) compose -f infra/docker-compose.yml --project-directory .
API := apps/api
WEB := apps/web

export NEXT_TELEMETRY_DISABLED := 1
export COREPACK_ENABLE_DOWNLOAD_PROMPT := 0

.DEFAULT_GOAL := help
.PHONY: help setup up down ps logs migrate sec-refresh fred-refresh prices-refresh prices-backfill news-refresh news-backfill buyback-evaluate buyback-backfill buyback-verify signals-backfill alerts-backfill regime-evaluate regime-backfill regime-verify replay-fixtures gen test test-unit test-integration e2e lint lint-api lint-web fmt dev-web

help: ## Show available targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-18s %s\n", $$1, $$2}'

setup: ## Install backend and frontend dependencies on the host
	cd $(API) && uv sync --locked
	cd $(WEB) && pnpm install --frozen-lockfile

up: ## Build and start the local stack; returns once every service is healthy
	$(COMPOSE) up -d --build --wait

down: ## Stop the local stack (data volumes are kept)
	$(COMPOSE) down

ps: ## Show service status
	$(COMPOSE) ps

logs: ## Follow service logs (filter with SERVICE=api)
	$(COMPOSE) logs -f --tail=100 $(SERVICE)

migrate: ## Apply Alembic migrations and sync config/sources.yaml (inside the api container)
	$(COMPOSE) exec -T api alembic upgrade head
	$(COMPOSE) exec -T api python -m autotrading.config_sync

sec-refresh: ## Queue an SEC EDGAR refresh now (tickers, then filings + XBRL facts per company)
	$(COMPOSE) exec -T api python -m autotrading.jobs.sec_refresh

fred-refresh: ## Queue a FRED / ALFRED refresh now (every enabled series in config/macro_series.yaml)
	$(COMPOSE) exec -T api python -m autotrading.jobs.fred_refresh

prices-refresh: ## Queue an Alpaca snapshot now and recent daily bars (needs APCA_* keys)
	$(COMPOSE) exec -T api python -m autotrading.jobs.prices_refresh

prices-backfill: ## Queue Alpaca daily bars since 2016, raw and split-adjusted (run once)
	$(COMPOSE) exec -T api python -m autotrading.jobs.prices_refresh --backfill

news-refresh: ## Queue GDELT (last 24 hours) and every enabled official feed now
	$(COMPOSE) exec -T api python -m autotrading.jobs.news_refresh

news-backfill: ## Queue GDELT news runs for each of the last 14 days (run once)
	$(COMPOSE) exec -T api python -m autotrading.jobs.news_refresh --backfill

buyback-evaluate: ## Queue a buyback state evaluation of every universe equity now (M1.4b)
	$(COMPOSE) exec -T api python -m autotrading.jobs.buyback_evaluate

buyback-backfill: ## Queue buyback state evaluations at every month end since 2021, marked backfilled (run once)
	$(COMPOSE) exec -T api python -m autotrading.jobs.buyback_evaluate --backfill

buyback-verify: ## Recompute the latest 20 stored buyback state assignments and report any that differ
	$(COMPOSE) exec -T api python -m autotrading.jobs.buyback_evaluate --verify 20

signals-backfill: ## Store the signals of buyback state assignments made before M1.6 (run once)
	$(COMPOSE) exec -T api python -m autotrading.jobs.signals_backfill

alerts-backfill: ## Store convergence levels and alerts for buyback assignments made before M1.7 (run once)
	$(COMPOSE) exec -T api python -m autotrading.jobs.alerts_backfill

regime-evaluate: ## Queue a macro regime assessment now (M2.1)
	$(COMPOSE) exec -T api python -m autotrading.jobs.regime_evaluate

regime-backfill: ## Queue regime assessments at every month end since 2016, marked backfilled (run once)
	$(COMPOSE) exec -T api python -m autotrading.jobs.regime_evaluate --backfill

regime-verify: ## Recompute the latest 20 stored regime assessments and report any that differ
	$(COMPOSE) exec -T api python -m autotrading.jobs.regime_evaluate --verify 20

factors-evaluate: ## Queue factor snapshots of every universe instrument now (M2.2)
	$(COMPOSE) exec -T api python -m autotrading.jobs.factors_evaluate

factors-backfill: ## Queue factor snapshots at every session since 2016, marked backfilled (run once)
	$(COMPOSE) exec -T api python -m autotrading.jobs.factors_evaluate --backfill

factors-verify: ## Recompute the latest 20 and 200 random stored factor snapshots (and those around splits)
	$(COMPOSE) exec -T api python -m autotrading.jobs.factors_evaluate --verify 20 --sample 200

replay-fixtures: ## CI only: load the recorded SEC, FRED, Alpaca and news fixtures into the stack database
	cd $(API) && uv run python -m tests.replay

gen: ## Regenerate apps/web/src/generated (glossary + API types) and apps/web/openapi.json
	cd $(API) && uv run python -m autotrading.openapi_dump ../web/openapi.json
	cd $(WEB) && pnpm -s gen

test: test-unit test-integration ## Full test suite (needs `make up`)

test-unit: ## Backend and frontend unit tests (no stack needed)
	cd $(API) && uv run pytest -m "not integration"
	cd $(WEB) && pnpm -s test

test-integration: ## Tests against the running stack; fails, never skips, if it is down
	cd $(API) && uv run pytest -m integration

e2e: ## Playwright browser tests against the running stack (needs `make up` + `make migrate`)
	cd $(WEB) && pnpm exec playwright test

lint: lint-api lint-web ## ruff, mypy, eslint, tsc

lint-api: ## Backend lint and type checks (mypy --strict on domain/)
	cd $(API) && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run mypy --strict src/autotrading/domain

lint-web: ## Frontend lint and type checks
	cd $(WEB) && pnpm -s lint && pnpm -s typecheck

fmt: ## Auto-format and auto-fix
	cd $(API) && uv run ruff format . && uv run ruff check --fix .
	cd $(WEB) && pnpm -s exec eslint --fix .

dev-web: ## Next.js dev server on http://127.0.0.1:3000 with hot reload (host)
	cd $(WEB) && pnpm dev
