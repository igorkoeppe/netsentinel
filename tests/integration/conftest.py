"""Shared fixtures for PostgreSQL integration tests.

Configuration
-------------
Set the ``TEST_DATABASE_URL`` environment variable to a PostgreSQL DSN that
points to a **dedicated test database** (not the development database)::

    TEST_DATABASE_URL=postgresql+asyncpg://netsentinel:netsentinel@localhost:5432/netsentinel_test

If the variable is absent, every test marked ``@pytest.mark.integration``
will be skipped automatically.  This ensures that ``pytest`` (the default
development command) never fails due to an unavailable database.

Isolation strategy
------------------
Each test receives a fresh ``AsyncSession`` that operates inside a
transaction.  The transaction is **rolled back** at the end of the test,
leaving the database in exactly the state it was in before the test ran.
No persistent data is written across tests; no explicit DELETE / TRUNCATE is
required.

Schema
------
``Base.metadata.create_all()`` is used instead of running Alembic migrations.
This is acceptable for an isolated test database because:

1. The test DB is throwaway — the schema can be wiped and recreated freely.
2. Adding full Alembic orchestration here would add complexity not justified
   at this development stage.
3. The Alembic migration itself is separately validated against PostgreSQL real
   in a different context.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    create_async_engine,
)

import app.models  # noqa: F401 — registers all ORM models with Base.metadata
from app.db.base import Base
from app.repositories.host import HostRepository
from app.repositories.monitoring_event import MonitoringEventRepository
from app.repositories.scan import ScanRepository

# ---------------------------------------------------------------------------
# Environment / skip logic
# ---------------------------------------------------------------------------

_TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")


def _require_pg() -> None:
    """Skip the current test if TEST_DATABASE_URL is not configured."""
    if not _TEST_DATABASE_URL:
        pytest.skip(
            "TEST_DATABASE_URL not set — skipping PostgreSQL integration test. "
            "Run with: TEST_DATABASE_URL=postgresql+asyncpg://... pytest -m integration"
        )


# ---------------------------------------------------------------------------
# Session-scoped engine + schema creation
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def pg_engine():  # type: ignore[return]
    """Create an engine and set up the schema once per test session.

    The engine is disposed after all integration tests finish.
    """
    _require_pg()

    engine = create_async_engine(_TEST_DATABASE_URL, echo=False, future=True)

    # Create all tables.  Idempotent: ``checkfirst=True`` skips existing ones.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, checkfirst=True)

    yield engine

    await engine.dispose()


# ---------------------------------------------------------------------------
# Function-scoped transactional session (rollback after each test)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def pg_connection(pg_engine):  # type: ignore[return]
    """Provide a raw connection with a SAVEPOINT for per-test rollback."""
    async with pg_engine.connect() as conn:
        await conn.begin()
        yield conn
        await conn.rollback()


@pytest_asyncio.fixture()
async def pg_session(pg_connection: AsyncConnection) -> AsyncSession:  # type: ignore[return]
    """Provide an AsyncSession bound to the per-test rolled-back connection."""
    session = AsyncSession(
        bind=pg_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    yield session  # type: ignore[misc]
    await session.close()


# ---------------------------------------------------------------------------
# Repository fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def host_repo(pg_session: AsyncSession) -> HostRepository:  # type: ignore[return]
    """Return a HostRepository wired to the per-test session."""
    return HostRepository(pg_session)


@pytest_asyncio.fixture()
async def scan_repo(pg_session: AsyncSession) -> ScanRepository:  # type: ignore[return]
    """Return a ScanRepository wired to the per-test session."""
    return ScanRepository(pg_session)


@pytest_asyncio.fixture()
async def event_repo(pg_session: AsyncSession) -> MonitoringEventRepository:  # type: ignore[return]
    """Return a MonitoringEventRepository wired to the per-test session."""
    return MonitoringEventRepository(pg_session)
