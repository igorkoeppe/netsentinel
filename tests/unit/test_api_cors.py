"""Unit tests for opt-in CORS middleware."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import create_app


@pytest.mark.asyncio
async def test_cors_disabled_by_default() -> None:
    """When API_CORS_ORIGINS is empty, CORS headers are not present."""
    with patch.object(settings, "API_CORS_ORIGINS", ""):
        test_app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/v1/health/live",
                headers={"Origin": "http://localhost:3000"},
            )
            assert resp.status_code == 200
            assert "access-control-allow-origin" not in resp.headers


@pytest.mark.asyncio
async def test_cors_enabled_for_explicit_origins() -> None:
    """Configured origins receive CORS headers; unconfigured origins do not."""
    with patch.object(
        settings,
        "API_CORS_ORIGINS",
        "http://localhost:3000,http://localhost:5173",
    ):
        test_app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            # Allowed origin
            resp_allowed = await client.get(
                "/api/v1/health/live",
                headers={"Origin": "http://localhost:3000"},
            )
            assert resp_allowed.status_code == 200
            assert (
                resp_allowed.headers.get("access-control-allow-origin")
                == "http://localhost:3000"
            )

            # Disallowed origin
            resp_disallowed = await client.get(
                "/api/v1/health/live",
                headers={"Origin": "http://malicious-site.example.com"},
            )
            assert resp_disallowed.status_code == 200
            assert "access-control-allow-origin" not in resp_disallowed.headers


@pytest.mark.asyncio
async def test_cors_preflight_options() -> None:
    """Preflight OPTIONS request returns appropriate CORS headers."""
    with patch.object(
        settings,
        "API_CORS_ORIGINS",
        "http://localhost:5173",
    ):
        test_app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            resp = await client.options(
                "/api/v1/health/live",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "X-API-Key",
                },
            )
            assert resp.status_code == 200
            assert (
                resp.headers.get("access-control-allow-origin")
                == "http://localhost:5173"
            )
            allow_headers = resp.headers.get("access-control-allow-headers", "")
            assert "X-API-Key" in allow_headers or "x-api-key" in allow_headers.lower()
