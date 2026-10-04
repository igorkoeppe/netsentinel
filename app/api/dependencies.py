"""FastAPI dependencies for NetSentinel REST API."""

from __future__ import annotations

import secrets
from collections.abc import AsyncGenerator

from fastapi import Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import APIError
from app.core.config import settings
from app.db.session import get_db_session


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an async database session dependency.

    Yields a session borrowed from the engine's connection pool.
    Transactions are NOT committed automatically here — read operations remain
    read-only, and mutation services explicitly manage their own commit/rollback.
    """
    async with get_db_session() as session:
        yield session


def require_read_auth(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    """Authentication policy for read-only endpoints.

    - If API_KEY is not configured: request is allowed without authentication
      (permitting local development without friction).
    - If API_KEY is configured: X-API-Key header is strictly enforced.
    """
    configured_key = settings.get_api_key()
    if configured_key is None:
        return

    if not x_api_key or not secrets.compare_digest(x_api_key, configured_key):
        raise APIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="UNAUTHORIZED",
            message="Invalid or missing API key.",
        )


def require_mutation_auth(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    """Authentication policy for mutation endpoints (acknowledge, resolve).

    - If API_KEY is not configured: mutations are disabled for safety (HTTP 503).
    - If API_KEY is configured: valid X-API-Key header is strictly required (HTTP 401).
    """
    configured_key = settings.get_api_key()
    if configured_key is None:
        raise APIError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="MUTATIONS_DISABLED",
            message="API mutations are disabled because no API key is configured.",
        )

    if not x_api_key or not secrets.compare_digest(x_api_key, configured_key):
        raise APIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="UNAUTHORIZED",
            message="Invalid or missing API key.",
        )
