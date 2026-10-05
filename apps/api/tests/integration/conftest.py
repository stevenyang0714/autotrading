import os
from collections.abc import Callable, Iterator
from pathlib import Path
from uuid import UUID, uuid4

import httpx2 as httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from autotrading.db.models import Entity, Source
from autotrading.settings import get_settings
from tests.factories import TEST_SOURCE_ID

API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000")
API_DIR = Path(__file__).resolve().parents[2]
# Throwaway databases match this pattern; the development database never does.
TEST_DB_LIKE = r"autotrading\_%\_test"


@pytest.fixture(scope="session")
def api_url() -> str:
    """Fail loudly (never skip) when the stack is down, so a broken stack can't pass CI."""
    try:
        httpx.get(f"{API_URL}/health/live", timeout=3).raise_for_status()
    except httpx.HTTPError:
        pytest.fail(
            f"Local stack is not reachable at {API_URL}. Run `make up` first.", pytrace=False
        )
    return API_URL


def server_url() -> URL:
    return make_url(get_settings().database_url.get_secret_value())


def alembic_config(url: URL) -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.attributes["database_url"] = url.render_as_string(hide_password=False)
    return config


@pytest.fixture(scope="session")
def admin_engine() -> Iterator[Engine]:
    """AUTOCOMMIT connection to the maintenance database: CREATE/DROP DATABASE can't run in a
    transaction."""
    engine = create_engine(server_url().set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            leftovers = conn.scalars(
                text("SELECT datname FROM pg_database WHERE datname LIKE :pattern"),
                {"pattern": TEST_DB_LIKE},
            ).all()
            for name in leftovers:  # from a crashed earlier run
                conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    except OperationalError:
        pytest.fail("Database is not reachable. Run `make up` first.", pytrace=False)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def database_factory(admin_engine: Engine) -> Iterator[Callable[[], URL]]:
    """Create empty databases from template0, so migrations really start from nothing."""
    created: list[str] = []

    def create() -> URL:
        name = f"autotrading_{uuid4().hex[:10]}_test"
        if not name.endswith("_test") or name == server_url().database:
            raise RuntimeError("refusing to use a non-test database name")
        with admin_engine.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}" TEMPLATE template0'))
        created.append(name)
        return server_url().set(database=name)

    yield create
    with admin_engine.connect() as conn:
        for name in created:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture(scope="session")
def migrated_url(database_factory: Callable[[], URL]) -> URL:
    url = database_factory()
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture(scope="session")
def engine(migrated_url: URL) -> Iterator[Engine]:
    engine = create_engine(migrated_url)
    with Session(engine) as session:
        session.add(
            Source(
                id=TEST_SOURCE_ID,
                name="Test source",
                url="https://example.com",
                tier=1,
                license_status="public",
                update_cadence="daily",
                freshness_sla_seconds=86400,
            )
        )
        session.commit()
    yield engine
    engine.dispose()


@pytest.fixture
def entity_id(engine: Engine) -> UUID:
    """A fresh entity per test: facts can't be deleted, so tests isolate by key."""
    with Session(engine) as session:
        entity = Entity(name=f"Test Co {uuid4().hex[:6]}", entity_type="company", country="US")
        session.add(entity)
        session.commit()
        return entity.id
