"""PostgreSQL / TimescaleDB engines and health probe."""

from sqlalchemy import Engine, NullPool, create_engine, text

from autotrading.infra.probes import PROBE_TIMEOUT_SECONDS, ProbeResult, run_probe
from autotrading.settings import Settings

# Connection budget: the local Postgres allows 25 connections (timescaledb-tune sizes
# max_connections from TS_TUNE_MEMORY=1GB). An instrument page makes 13 API calls at once,
# so the API keeps 13 connections open for reuse instead of opening and closing them on
# every page load; its ceiling stays 15, as before. The worker (2 threads) and the
# scheduler keep 2 each; the scheduler's catch-up burst (up to 10 jobs at once on
# APScheduler's threads) may briefly open more. That is about 17 connections in steady
# state, which leaves room for the health probe, migrations, backups and test runs.
POOL_SIZE = 13
MAX_OVERFLOW = 2
BACKGROUND_POOL_SIZE = 2
BACKGROUND_MAX_OVERFLOW = 8
POOL_TIMEOUT_SECONDS = 30
# A busy database (e.g. the scheduler's catch-up burst after the Mac wakes) can take
# longer than the probe's 2 s to accept a new connection; a request waits rather than
# failing with a 500. The health probe keeps PROBE_TIMEOUT_SECONDS.
CONNECT_TIMEOUT_SECONDS = 10


class TimescaleUnavailableError(RuntimeError):
    """The database is reachable but the timescaledb extension is not installable."""


def make_engine(settings: Settings) -> Engine:
    """Engine for API requests and one-off commands."""
    return _pooled_engine(settings, POOL_SIZE, MAX_OVERFLOW)


def make_background_engine(settings: Settings) -> Engine:
    """Engine for the worker and scheduler processes (jobs/actors.py)."""
    return _pooled_engine(settings, BACKGROUND_POOL_SIZE, BACKGROUND_MAX_OVERFLOW)


def _pooled_engine(settings: Settings, pool_size: int, max_overflow: int) -> Engine:
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=POOL_TIMEOUT_SECONDS,
        connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS},
    )


def make_probe_engine(settings: Settings) -> Engine:
    """Engine for the health probe: no pool, so every probe opens a fresh connection with
    the probe timeout and never waits behind busy request connections."""
    return create_engine(
        settings.database_url.get_secret_value(),
        poolclass=NullPool,
        connect_args={"connect_timeout": PROBE_TIMEOUT_SECONDS},
    )


def probe_database(engine: Engine) -> ProbeResult:
    def check() -> str:
        with engine.connect() as conn:
            version = conn.execute(
                text(
                    "SELECT default_version FROM pg_available_extensions WHERE name = 'timescaledb'"
                )
            ).scalar_one_or_none()
        if version is None:
            raise TimescaleUnavailableError
        return f"timescaledb {version} available"

    return run_probe(check)
