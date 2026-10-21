"""Engine settings (no database needed: creating an engine does not connect)."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import Engine, NullPool, QueuePool, event

from autotrading.infra.db import (
    BACKGROUND_MAX_OVERFLOW,
    BACKGROUND_POOL_SIZE,
    CONNECT_TIMEOUT_SECONDS,
    MAX_OVERFLOW,
    POOL_SIZE,
    make_background_engine,
    make_engine,
    make_probe_engine,
)
from autotrading.infra.probes import PROBE_TIMEOUT_SECONDS
from autotrading.settings import Settings

# The instrument page's Promise.all (apps/web/src/app/instruments/[ticker]/page.tsx).
INSTRUMENT_PAGE_API_CALLS = 13
# Before the pool was sized for page loads the API could hold 15 connections; the
# connection budget (infra/db.py) counts on that ceiling.
API_CONNECTION_CEILING = 15
# APScheduler's default thread pool: a catch-up burst runs at most this many jobs at once.
SCHEDULER_THREADS = 10
# Connections outside the stack's pools in the budget (infra/db.py): the health probe's,
# an integration test run's, and migrations' or backups'.
PROBE_CONNECTIONS = 1
TEST_RUN_CONNECTIONS = 6
ADMIN_CONNECTIONS = 3
COMPOSE_FILE = Path(__file__).resolve().parents[4] / "infra" / "docker-compose.yml"


class Captured(Exception):
    """Raised instead of connecting, once the driver's arguments are known."""


def connect_arguments(engine: Engine) -> dict[str, Any]:
    """The keyword arguments the driver would receive, captured without connecting."""
    captured: dict[str, Any] = {}

    @event.listens_for(engine, "do_connect")
    def capture(dialect: object, record: object, cargs: object, cparams: dict[str, Any]) -> None:
        captured.update(cparams)
        raise Captured

    with pytest.raises(Captured):
        engine.connect()
    return captured


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_a_page_load_reuses_pooled_connections(settings: Settings) -> None:
    engine = make_engine(settings)
    assert isinstance(engine.pool, QueuePool)
    assert engine.pool.size() == POOL_SIZE >= INSTRUMENT_PAGE_API_CALLS
    assert POOL_SIZE + MAX_OVERFLOW <= API_CONNECTION_CEILING
    assert engine.pool._max_overflow == MAX_OVERFLOW


def test_the_worker_and_scheduler_keep_few_connections_open(settings: Settings) -> None:
    engine = make_background_engine(settings)
    assert isinstance(engine.pool, QueuePool)
    assert engine.pool.size() == BACKGROUND_POOL_SIZE < POOL_SIZE
    assert engine.pool._max_overflow == BACKGROUND_MAX_OVERFLOW
    assert BACKGROUND_POOL_SIZE + BACKGROUND_MAX_OVERFLOW == SCHEDULER_THREADS


@pytest.mark.parametrize("factory", [make_engine, make_background_engine])
def test_request_and_job_connections_wait_longer_than_the_health_probe(
    settings: Settings, factory: Callable[[Settings], Engine]
) -> None:
    assert connect_arguments(factory(settings))["connect_timeout"] == CONNECT_TIMEOUT_SECONDS
    assert CONNECT_TIMEOUT_SECONDS > PROBE_TIMEOUT_SECONDS


def test_the_health_probe_opens_its_own_connection_with_the_probe_timeout(
    settings: Settings,
) -> None:
    engine = make_probe_engine(settings)
    assert isinstance(engine.pool, NullPool)
    assert connect_arguments(engine)["connect_timeout"] == PROBE_TIMEOUT_SECONDS


def test_the_worker_and_scheduler_share_one_pool_across_their_jobs() -> None:
    # Importing the actors connects to nothing (Redis and the database are used lazily).
    from autotrading.jobs import actors

    assert actors.ingestion_runner().sessions is actors.sessions()
    engine = actors.sessions().kw["bind"]
    assert engine.pool.size() == BACKGROUND_POOL_SIZE


def database_max_connections() -> int:
    """The max_connections flag on the db service (infra/docker-compose.yml)."""
    command = yaml.safe_load(COMPOSE_FILE.read_text())["services"]["db"]["command"]
    (setting,) = [arg for arg in command if arg.startswith("max_connections=")]
    return int(setting.removeprefix("max_connections="))


def test_every_pool_at_its_ceiling_fits_the_database_connection_limit() -> None:
    api = POOL_SIZE + MAX_OVERFLOW + PROBE_CONNECTIONS
    worker_and_scheduler = 2 * (BACKGROUND_POOL_SIZE + BACKGROUND_MAX_OVERFLOW)
    others = TEST_RUN_CONNECTIONS + ADMIN_CONNECTIONS
    # Two APIs: the stack's and a second container to test a branch (as on 2026-10-19).
    assert 2 * api + worker_and_scheduler + others <= database_max_connections()
