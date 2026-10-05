"""PostgreSQL / TimescaleDB engine and health probe."""

from sqlalchemy import Engine, create_engine, text

from autotrading.infra.probes import PROBE_TIMEOUT_SECONDS, ProbeResult, run_probe
from autotrading.settings import Settings


class TimescaleUnavailableError(RuntimeError):
    """The database is reachable but the timescaledb extension is not installable."""


def make_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
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
