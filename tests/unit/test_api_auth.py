"""Unit tests for API Key authentication policy and headers."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_session
from app.core.config import Settings
from app.main import app
from app.models.security_alert import SecurityAlertRecord


@pytest.fixture
def mock_db_session() -> AsyncMock:
    session = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_health_endpoints_always_public(mock_db_session: AsyncMock) -> None:
    """Health endpoints are public even when API_KEY is configured."""
    with patch.object(Settings, "get_api_key", return_value="secret-key-123"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp_legacy = await client.get("/health")
            assert resp_legacy.status_code == 200

            resp_live = await client.get("/api/v1/health/live")
            assert resp_live.status_code == 200


@pytest.mark.asyncio
async def test_read_endpoints_unauthenticated_when_api_key_empty(
    mock_db_session: AsyncMock,
) -> None:
    """When API_KEY is not configured, read endpoints are accessible without auth."""
    app.dependency_overrides[get_session] = lambda: mock_db_session
    try:
        with (
            patch.object(Settings, "get_api_key", return_value=None),
            patch(
                "app.services.host_query.HostQueryService.list_hosts",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/hosts")
                assert resp.status_code == 200
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_read_endpoints_require_api_key_when_configured(
    mock_db_session: AsyncMock,
) -> None:
    """When API_KEY is configured, read endpoints require valid X-API-Key."""
    app.dependency_overrides[get_session] = lambda: mock_db_session
    try:
        with (
            patch.object(Settings, "get_api_key", return_value="test-secret-key"),
            patch(
                "app.services.host_query.HostQueryService.list_hosts",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # 1. Missing header -> 401
                resp_missing = await client.get("/api/v1/hosts")
                assert resp_missing.status_code == 401
                assert (
                    resp_missing.json()["error"]["message"]
                    == "Invalid or missing API key."
                )

                # 2. Key passed in query string -> ignored, still 401
                resp_query = await client.get("/api/v1/hosts?X-API-Key=test-secret-key")
                assert resp_query.status_code == 401

                # 3. Wrong key -> 401
                resp_wrong = await client.get(
                    "/api/v1/hosts", headers={"X-API-Key": "wrong-key"}
                )
                assert resp_wrong.status_code == 401
                assert resp_wrong.json()["error"]["code"] == "UNAUTHORIZED"

                # 4. Valid key -> 200
                resp_valid = await client.get(
                    "/api/v1/hosts", headers={"X-API-Key": "test-secret-key"}
                )
                assert resp_valid.status_code == 200
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_mutation_endpoints_disabled_when_api_key_empty(
    mock_db_session: AsyncMock,
) -> None:
    """Mutations are disabled (HTTP 503) when no API key is configured."""
    app.dependency_overrides[get_session] = lambda: mock_db_session
    try:
        with patch.object(Settings, "get_api_key", return_value=None):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/v1/alerts/1/acknowledge")
                assert resp.status_code == 503
                body = resp.json()
                assert body["error"]["code"] == "MUTATIONS_DISABLED"
                assert "disabled" in body["error"]["message"].lower()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_mutation_endpoints_require_valid_key_when_configured(
    mock_db_session: AsyncMock,
) -> None:
    """Mutations require valid X-API-Key when configured."""
    app.dependency_overrides[get_session] = lambda: mock_db_session
    mock_record = AsyncMock(spec=SecurityAlertRecord)
    mock_record.id = 1
    mock_record.alert_type = "UNEXPECTED_OPEN_PORT"
    mock_record.severity = "HIGH"
    mock_record.status = "ACKNOWLEDGED"
    mock_record.host = None
    mock_record.port = 80
    mock_record.message = "test"
    mock_record.created_at = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)
    mock_record.acknowledged_at = None
    mock_record.resolved_at = None

    try:
        with (
            patch.object(Settings, "get_api_key", return_value="mutation-secret"),
            patch(
                "app.services.alert_triage.AlertTriageService.acknowledge",
                new_callable=AsyncMock,
                return_value=mock_record,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # Missing header -> 401
                resp_missing = await client.post("/api/v1/alerts/1/acknowledge")
                assert resp_missing.status_code == 401

                # Incorrect header -> 401
                resp_wrong = await client.post(
                    "/api/v1/alerts/1/acknowledge",
                    headers={"X-API-Key": "wrong-key"},
                )
                assert resp_wrong.status_code == 401

                # Correct header -> 200
                resp_valid = await client.post(
                    "/api/v1/alerts/1/acknowledge",
                    headers={"X-API-Key": "mutation-secret"},
                )
                assert resp_valid.status_code == 200
    finally:
        app.dependency_overrides.clear()
