"""Alembic environment configuration for NetSentinel.

Key design decisions:
- ``DATABASE_URL`` is read from ``settings`` at runtime — never hardcoded.
- The async engine requires ``run_sync`` to execute migrations; we use
  ``asyncio.run`` to bridge the sync Alembic API with the async driver.
- Both ``run_migrations_offline`` and ``run_migrations_online`` are implemented
  as required by Alembic, but the async online mode is the primary path.
- ``include_schemas=False`` keeps things simple; all tables are in the default
  schema for now.
"""

import asyncio
import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# Import all models to populate Base.metadata before Alembic inspects it.
import app.models  # noqa: F401 — side effect: registers all ORM models
from app.core.config import settings
from app.db.base import Base

# Alembic Config object — gives access to values in alembic.ini.
config = context.config

# Configure logging from alembic.ini if a logging section is present.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")

# The metadata object that Alembic will diff against the live schema.
target_metadata = Base.metadata


def _get_url() -> str:
    """Return DATABASE_URL from application settings.

    Raises:
        RuntimeError: If DATABASE_URL is not configured.
    """
    url = settings.DATABASE_URL
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Configure it before running Alembic commands."
        )
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    In offline mode Alembic generates SQL scripts without connecting to
    the database.  Useful for reviewing or applying migrations manually.
    """
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: object) -> None:
    """Execute migrations inside a synchronous connection context."""
    context.configure(connection=connection, target_metadata=target_metadata)  # type: ignore[arg-type]
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations asynchronously using the asyncpg driver."""
    url = _get_url()
    connectable = create_async_engine(url, future=True)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connected to a live database)."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
