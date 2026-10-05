"""Alembic environment.

The database URL comes from Settings (DATABASE_URL). Tests pass a throwaway database through
`config.attributes["database_url"]`. Never log the URL: it contains credentials.
"""

from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import create_engine, pool

from autotrading.db import models  # noqa: F401  (registers tables on Base.metadata)
from autotrading.db.base import Base
from autotrading.settings import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def database_url() -> str:
    override = config.attributes.get("database_url")
    if isinstance(override, str):
        return override
    return get_settings().database_url.get_secret_value()


def include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    # Exclusion constraints (ex_*) are created in migrations only; their backing GiST indexes
    # are reflected as plain indexes and would otherwise show up as drift.
    return not (type_ == "index" and reflected and name is not None and name.startswith("ex_"))


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        include_object=include_object,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
