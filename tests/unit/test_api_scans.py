"""Unit tests for /api/v1/scans endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_session
from app.core.config import Settings
from app.main import app
from app.services.history import (
    AlertSummary,
    EventSummary,
    PortResultSummary,
    ScanDetailsResult,
)

_NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def mock_db_session() -> AsyncMock:
    return AsyncMock()


@pytest.mark.asyncio
async def test_get_scan_details_success(mock_db_session: AsyncMock) -> None:
    app.dependency_overrides[get_session] = lambda: mock_db_session
    details = ScanDetailsResult(
        scan_id=42,
        status="available",
        response_time_ms=2.4,
        started_at=_NOW,
        finished_at=_NOW,
        target="10.0.0.1",
        ports=[
            PortResultSummary(port=80, status="open", response_time_ms=2.4),
            PortResultSummary(port=443, status="closed", response_time_ms=5.0),
        ],
        events=[
            EventSummary(
                event_type="port_opened",
                port=80,
                previous_state="closed",
                current_state="open",
                created_at=_NOW,
            )
        ],
        alerts=[
            AlertSummary(
                id=1,
                alert_type="unexpected_open_port",
                severity="high",
                message="Unexpected open port 80",
                port=80,
                created_at=_NOW,
                monitoring_event_id=10,
            )
        ],
    )

    try:
        with (
            patch.object(Settings, "get_api_key", return_value=None),
            patch(
                "app.services.history.HistoryService.get_scan_details",
                new_callable=AsyncMock,
                return_value=details,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/scans/42")
                assert resp.status_code == 200
                data = resp.json()
                assert data["id"] == 42
                assert data["target"] == "10.0.0.1"
                assert data["status"] == "AVAILABLE"
                assert len(data["ports"]) == 2
                assert data["ports"][0]["port"] == 80
                assert data["ports"][0]["status"] == "OPEN"
                assert len(data["events"]) == 1
                assert data["events"][0]["event_type"] == "PORT_OPENED"
                assert len(data["alerts"]) == 1
                assert data["alerts"][0]["severity"] == "HIGH"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_scan_details_not_found(mock_db_session: AsyncMock) -> None:
    app.dependency_overrides[get_session] = lambda: mock_db_session
    try:
        with (
            patch.object(Settings, "get_api_key", return_value=None),
            patch(
                "app.services.history.HistoryService.get_scan_details",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/scans/999")
                assert resp.status_code == 404
                assert resp.json()["error"]["code"] == "SCAN_NOT_FOUND"
                assert "Scan 999 not found" in resp.json()["error"]["message"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_scan_details_invalid_id() -> None:
    with patch.object(Settings, "get_api_key", return_value=None):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/scans/0")
            assert resp.status_code == 422
            assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
