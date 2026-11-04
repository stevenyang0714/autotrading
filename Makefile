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
.PHONY: help setup up down ps logs migrate sec-refresh fred-refresh prices-refresh prices-backfill news-refresh news-backfill buyback-evaluate buyback-backfill buyback-verify signals-backfill alerts-backfill regime-evaluate regime-backfill regime-verify factors-evaluate factors-backfill factors-verify portfolio-snapshot risk-verify holdings-snapshot holdings-verify rotation-evaluate rotation-backfill rotation-verify momentum-evaluate momentum-backfill momentum-verify alerts-deliver alerts-digest telegram-check twse-refresh twse-factors twse-factors-backfill twse-rank finmind-refresh finmind-backfill finmind-listed-backfill screens-evaluate screens-backfill screens-verify backtest-run backtest-verify db-backup db-restore-check replay-fixtures gen test test-unit test-integration e2e lint lint-api lint-web fmt dev-web

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

regime-backfill: ## Queue regime assessments at every session close and month end since 2016, marked backfilled (once per rule version)
	$(COMPOSE) exec -T api python -m autotrading.jobs.regime_evaluate --backfill

regime-verify: ## Recompute the latest 20 stored regime assessments of each rule version and report any that differ
	$(COMPOSE) exec -T api python -m autotrading.jobs.regime_evaluate --verify 20

factors-evaluate: ## Queue factor snapshots of every universe instrument now (M2.2)
	$(COMPOSE) exec -T api python -m autotrading.jobs.factors_evaluate

factors-backfill: ## Queue factor snapshots at every session since 2016, marked backfilled (run once)
	$(COMPOSE) exec -T api python -m autotrading.jobs.factors_evaluate --backfill

factors-verify: ## Recompute the latest 20 and 200 random stored factor snapshots (and those around splits)
	$(COMPOSE) exec -T api python -m autotrading.jobs.factors_evaluate --verify 20 --sample 200

portfolio-snapshot: ## Queue a paper portfolio snapshot (and its drawdown alert) now (M2.3)
	$(COMPOSE) exec -T api python -m autotrading.jobs.risk_evaluate

risk-verify: ## Recompute the latest 20 and 100 random stored risk checks and report any that differ
	$(COMPOSE) exec -T api python -m autotrading.jobs.risk_evaluate --verify 20 --sample 100

holdings-snapshot: ## Queue a snapshot of the recorded real holdings now (M3.10)
	$(COMPOSE) exec -T api python -m autotrading.jobs.holdings_snapshot

holdings-verify: ## Recompute the latest 20 and 100 random holdings snapshots and report any that differ
	$(COMPOSE) exec -T api python -m autotrading.jobs.holdings_snapshot --verify 20 --sample 100

rotation-evaluate: ## Queue an S3 ETF rotation assessment now (M2.4)
	$(COMPOSE) exec -T api python -m autotrading.jobs.rotation_evaluate

rotation-backfill: ## Queue the S3 rotation at every session close and month end since 2017, in order, marked backfilled (once per rule version)
	$(COMPOSE) exec -T api python -m autotrading.jobs.rotation_evaluate --backfill

rotation-verify: ## Recompute the latest 200 stored rotation assessments of each rule version and report any that differ
	$(COMPOSE) exec -T api python -m autotrading.jobs.rotation_evaluate --verify 200

twse-refresh: ## Queue the Taiwan universe's latest session from the TWSE OpenAPI now (M3.7)
	$(COMPOSE) exec -T api python -m autotrading.jobs.twse_refresh

twse-factors: ## Queue the Taiwan factor snapshots now (definitions 0.2.0 against 0050, M3.7)
	$(COMPOSE) exec -T api python -m autotrading.jobs.twse_refresh --factors

twse-factors-backfill: ## Queue Taiwan factor snapshots at every 0050 session since 2016 (M3.7b; run once)
	$(COMPOSE) exec -T api python -m autotrading.jobs.twse_refresh --factors-backfill

finmind-refresh: ## Queue the Taiwan institutional flows and foreign holdings from FinMind now (M3.7b)
	$(COMPOSE) exec -T api python -m autotrading.jobs.finmind_refresh

finmind-backfill: ## Queue the one-time FinMind history (prices, margin, P/E, dividends, flows since 2016; M3.7b)
	$(COMPOSE) exec -T api python -m autotrading.jobs.finmind_refresh --backfill

finmind-listed-backfill: ## Queue the listed companies' FinMind history (DATASET=price|dividends; M3.11)
	$(COMPOSE) exec -T api python -m autotrading.jobs.finmind_refresh --listed-backfill $(if $(DATASET),--dataset $(DATASET),)

screens-evaluate: ## Queue the Taiwan screens of the newest stored session now (M3.11)
	$(COMPOSE) exec -T api python -m autotrading.jobs.screens_evaluate

screens-backfill: ## Queue the Taiwan screens at every stored session not judged yet (SINCE=YYYY-MM-DD; M3.11)
	$(COMPOSE) exec -T api python -m autotrading.jobs.screens_evaluate --backfill $(if $(SINCE),--since $(SINCE),)

screens-verify: ## Recompute the latest 20 judged Taiwan screen runs and compare (M3.11)
	$(COMPOSE) exec -T api python -m autotrading.jobs.screens_evaluate --verify 20

twse-rank: ## Print the TWSE market-cap ranking from the stored files against universe_tw.yaml
	$(COMPOSE) exec -T api python -m autotrading.jobs.twse_refresh --rank

alerts-deliver: ## Queue the Telegram delivery of pending alerts now (M3.0b; nothing without Telegram in .env)
	$(COMPOSE) exec -T api python -c "from autotrading.jobs import actors; actors.start_alert_delivery(manual=True)"

alerts-digest: ## Send this week's digest of rule candidates to Telegram now, once a week (M3.0c)
	$(COMPOSE) exec -T api python -c "from autotrading.jobs import actors; actors.start_digest(manual=True)"

telegram-check: ## Run on the Mac by Steven: list chats that wrote to the bot, or send a test message (M3.0b)
	cd $(API) && uv run python -m autotrading.jobs.telegram_check

momentum-evaluate: ## Queue an S4 momentum assessment now (M3.0)
	$(COMPOSE) exec -T api python -m autotrading.jobs.momentum_evaluate

momentum-backfill: ## Queue S4 at every session close and month end since 2017, in order, marked backfilled (once per rule version)
	$(COMPOSE) exec -T api python -m autotrading.jobs.momentum_evaluate --backfill

momentum-verify: ## Recompute the latest 200 stored S4 assessments of each rule version and report any that differ
	$(COMPOSE) exec -T api python -m autotrading.jobs.momentum_evaluate --verify 200

backtest-run: ## Queue the backtests of S1, S3 and S4 now (M2.5; performance withheld, OD-7)
	$(COMPOSE) exec -T api python -m autotrading.jobs.backtest_evaluate

backtest-verify: ## Recompute the latest 30 stored backtest runs and report any that differ
	$(COMPOSE) exec -T api python -m autotrading.jobs.backtest_evaluate --verify 30

db-backup: ## Back up the database and object store to $$BACKUP_DIR (default ~/autotrading-backups; ADR-034)
	./infra/backup.sh

db-restore-check: ## Restore the latest backup into a throwaway database and compare it with its manifest
	./infra/restore_check.sh

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
