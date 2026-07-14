"""Alembic migration environment (async).

Targets ``app.domain.Base.metadata`` and sources the database URL from the
application :class:`Settings` — the same URL the app uses — so migrations and
runtime can never drift onto different databases. Runs the engine in async
mode over psycopg3, matching the app.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Import the metadata target. Importing app.domain registers every model.
from app.core.config import get_settings
from app.domain import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the runtime DB URL from Settings into the Alembic config.
config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def do_run_migrations(connection: Connection) -> None:
    """Configure the context on a live connection and run migrations."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations within it."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        future=True,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a DBAPI connection (``--sql`` mode)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live async connection."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
