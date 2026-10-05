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
.PHONY: help setup up down ps logs migrate sec-refresh sec-replay gen test test-unit test-integration e2e lint lint-api lint-web fmt dev-web

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

sec-replay: ## CI only: load the recorded SEC fixtures (AAPL, XOM) into the stack database
	cd $(API) && uv run python -m tests.sec_replay

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
