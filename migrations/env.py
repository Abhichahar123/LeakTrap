"""Alembic environment for LeakTrace.

The database URL comes from DATABASE_URL (via backend.config), never from
alembic.ini. Tests may instead pass an open connection through
config.attributes["connection"].
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, create_engine, pool

import backend.models  # noqa: F401  (registers every table on Base.metadata)
from backend.config import settings
from backend.database import Base, DatabaseNotConfiguredError, require_postgresql_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def get_url() -> str:
    if not settings.database_url:
        raise DatabaseNotConfiguredError(
            "DATABASE_URL is not set. Export it before running Alembic, e.g. "
            "postgresql+psycopg://USER:PASSWORD@localhost:5432/leaktrace"
        )
    require_postgresql_url(settings.database_url)
    return settings.database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (alembic upgrade head --sql)."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_with_connection(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run_with_connection(connection)
        return

    engine = create_engine(get_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        _run_with_connection(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
