"""Unit tests for health, liveness, and readiness endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app


@pytest.mark.asyncio
async def test_legacy_health_endpoint() -> None:
    """Ensure legacy GET /health is preserved and returns HTTP 200."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["service"] == "netsentinel"


@pytest.mark.asyncio
async def test_liveness_endpoint_without_db() -> None:
    """GET /api/v1/health/live must succeed without accessing the database."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/health/live")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["service"] == "NetSentinel"
        assert "0.7.0" in body["version"]


@pytest.mark.asyncio
async def test_readiness_endpoint_db_available() -> None:
    """GET /api/v1/health/ready returns 200 when database is responsive."""
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock()

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_engine.connect.return_value.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("app.api.routes.health.get_engine", return_value=mock_engine),
        patch.object(
            settings,
            "DATABASE_URL",
            "postgresql+asyncpg://user:secret@localhost:5432/db",
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/health/ready")
            assert resp.status_code == 200
            assert resp.json() == {"status": "ready", "database": "available"}


@pytest.mark.asyncio
async def test_readiness_endpoint_unconfigured_db() -> None:
    """GET /api/v1/health/ready returns 503 when DATABASE_URL is empty."""
    with patch.object(settings, "DATABASE_URL", ""):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/health/ready")
            assert resp.status_code == 503
            assert resp.json() == {
                "status": "unavailable",
                "database": "not_configured",
            }


@pytest.mark.asyncio
async def test_readiness_endpoint_db_unavailable_sanitized() -> None:
    """GET /api/v1/health/ready returns 503 and no leaked credentials
    on DB connection error.
    """
    mock_engine = MagicMock()
    mock_engine.connect.side_effect = Exception(
        "password123 postgresql+asyncpg:// leaked"
    )

    with (
        patch("app.api.routes.health.get_engine", return_value=mock_engine),
        patch.object(
            settings,
            "DATABASE_URL",
            "postgresql+asyncpg://netsentinel:secret@127.0.0.1:5432/netsentinel",
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/health/ready")
            assert resp.status_code == 503
            body = resp.text
            assert "secret" not in body
            assert "password" not in body
            assert "postgresql" not in body
            assert resp.json() == {"status": "unavailable", "database": "unavailable"}
