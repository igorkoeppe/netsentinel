"""Async database engine and session factory.

Design decisions:
- The engine is created lazily via ``get_engine()`` — importing this module
  does NOT open any database connection.
- ``DATABASE_URL`` is read from settings at call time, not at import time.
- SQL echo is disabled to avoid leaking connection strings or query data to logs.
- ``expire_on_commit=False`` prevents lazy-load errors on detached instances
  after commits, which is the recommended default for async sessions.
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

logger = logging.getLogger(__name__)

# Module-level singletons — populated lazily, never at import time.
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return (and lazily create) the async SQLAlchemy engine.

    Raises:
        RuntimeError: If ``DATABASE_URL`` is not configured.
    """
    global _engine

    if _engine is None:
        url = settings.DATABASE_URL
        if not url:
            raise RuntimeError(
                "DATABASE_URL is not configured. "
                "Set it in your .env file or environment before using the database."
            )
        # echo=False — never log SQL that could contain sensitive data.
        _engine = create_async_engine(url, echo=False, future=True)
        logger.debug("Async database engine created.")

    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return (and lazily create) the async session factory."""
    global _session_factory

    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            class_=AsyncSession,
        )

    return _session_factory


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager providing a database session.

    Usage::

        async with get_db_session() as session:
            result = await session.execute(...)

    The session is automatically closed when the context exits.
    Exceptions are not swallowed — callers are responsible for rollback logic.
    """
    factory = get_session_factory()
    async with factory() as session:
        yield session
