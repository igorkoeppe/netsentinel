"""Unit tests for /api/v1/hosts endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_session
from app.core.config import Settings
from app.main import app
from app.services.history import HostHistoryResult, ScanHistorySummary
from app.services.host_query import HostItem

_NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def mock_db_session() -> AsyncMock:
    return AsyncMock()


@pytest.mark.asyncio
async def test_list_hosts_empty(mock_db_session: AsyncMock) -> None:
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
                data = resp.json()
                assert data["items"] == []
                assert data["limit"] == 20
                assert data["offset"] == 0
                assert data["count"] == 0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_hosts_populated_and_pagination(mock_db_session: AsyncMock) -> None:
    app.dependency_overrides[get_session] = lambda: mock_db_session
    sample_hosts = [
        HostItem(
            id=1,
            name="Gateway",
            address="192.168.1.1",
            enabled=True,
            created_at=_NOW,
            updated_at=_NOW,
        ),
        HostItem(
            id=2,
            name=None,
            address="10.0.0.1",
            enabled=False,
            created_at=_NOW,
            updated_at=None,
        ),
    ]

    try:
        with (
            patch.object(Settings, "get_api_key", return_value=None),
            patch(
                "app.services.host_query.HostQueryService.list_hosts",
                new_callable=AsyncMock,
                return_value=sample_hosts,
            ) as mock_list,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/hosts?limit=10&offset=5&enabled=true")
                assert resp.status_code == 200
                data = resp.json()
                assert len(data["items"]) == 2
                assert data["count"] == 2
                assert data["limit"] == 10
                assert data["offset"] == 5

                item1 = data["items"][0]
                assert item1["id"] == 1
                assert item1["name"] == "Gateway"
                assert item1["address"] == "192.168.1.1"
                assert item1["enabled"] is True
                assert "2026-10-04T12:00:00" in item1["created_at"]

                item2 = data["items"][1]
                assert item2["id"] == 2
                assert item2["name"] is None
                assert item2["updated_at"] is None

                mock_list.assert_awaited_once_with(limit=10, offset=5, enabled=True)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_hosts_validation_errors() -> None:
    with patch.object(Settings, "get_api_key", return_value=None):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # limit < 1
            r0 = await client.get("/api/v1/hosts?limit=0")
            assert r0.status_code == 422
            assert r0.json()["error"]["code"] == "VALIDATION_ERROR"

            # limit > 100
            r101 = await client.get("/api/v1/hosts?limit=101")
            assert r101.status_code == 422

            # offset < 0
            r_neg = await client.get("/api/v1/hosts?offset=-1")
            assert r_neg.status_code == 422


@pytest.mark.asyncio
async def test_get_host_history_success(mock_db_session: AsyncMock) -> None:
    app.dependency_overrides[get_session] = lambda: mock_db_session
    sample_history = HostHistoryResult(
        host_id=1,
        address="127.0.0.1",
        name="Localhost",
        enabled=True,
        scans=[
            ScanHistorySummary(
                scan_id=42,
                timestamp=_NOW,
                status="available",
                response_time_ms=1.5,
                port_count=4,
                event_count=1,
                alert_count=0,
            )
        ],
    )

    try:
        with (
            patch.object(Settings, "get_api_key", return_value=None),
            patch(
                "app.services.history.HistoryService.get_host_history",
                new_callable=AsyncMock,
                return_value=sample_history,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/hosts/127.0.0.1/history?limit=15")
                assert resp.status_code == 200
                data = resp.json()
                assert data["host_id"] == 1
                assert data["address"] == "127.0.0.1"
                assert len(data["scans"]) == 1
                scan = data["scans"][0]
                assert scan["scan_id"] == 42
                assert scan["status"] == "available"
                assert scan["response_time_ms"] == 1.5
                assert scan["alert_count"] == 0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_host_history_not_found(mock_db_session: AsyncMock) -> None:
    app.dependency_overrides[get_session] = lambda: mock_db_session
    try:
        with (
            patch.object(Settings, "get_api_key", return_value=None),
            patch(
                "app.services.history.HistoryService.get_host_history",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/hosts/192.168.1.99/history")
                assert resp.status_code == 404
                assert resp.json()["error"]["code"] == "HOST_NOT_FOUND"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_host_history_invalid_target() -> None:
    with patch.object(Settings, "get_api_key", return_value=None):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/hosts/invalid target with spaces/history")
            assert resp.status_code == 404
            assert resp.json()["error"]["code"] == "HOST_NOT_FOUND"
