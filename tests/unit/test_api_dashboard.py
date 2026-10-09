"""Unit tests for /api/v1/dashboard/summary endpoint."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_session
from app.core.config import Settings
from app.detection.alerts import AlertStatus, Severity
from app.main import app
from app.services.dashboard_query import (
    AlertsSummaryResult,
    DashboardSummaryResult,
    HostsSummaryResult,
    ScansSummaryResult,
)

_NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def mock_db_session() -> AsyncMock:
    return AsyncMock()


@pytest.mark.asyncio
async def test_dashboard_summary_empty(mock_db_session: AsyncMock) -> None:
    app.dependency_overrides[get_session] = lambda: mock_db_session
    empty_summary = DashboardSummaryResult(
        hosts=HostsSummaryResult(total=0, enabled=0, disabled=0),
        scans=ScansSummaryResult(total=0, last_scan_at=None),
        alerts=AlertsSummaryResult(
            total=0,
            by_status={s.value: 0 for s in AlertStatus},
            by_severity={s.name: 0 for s in Severity},
        ),
    )

    try:
        with (
            patch.object(Settings, "get_api_key", return_value=None),
            patch(
                "app.services.dashboard_query.DashboardQueryService.get_summary",
                new_callable=AsyncMock,
                return_value=empty_summary,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/dashboard/summary")
                assert resp.status_code == 200
                data = resp.json()
                assert data["hosts"] == {"total": 0, "enabled": 0, "disabled": 0}
                assert data["scans"] == {"total": 0, "last_scan_at": None}
                assert data["alerts"]["total"] == 0
                assert data["alerts"]["by_status"]["OPEN"] == 0
                assert data["alerts"]["by_severity"]["HIGH"] == 0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_dashboard_summary_populated(mock_db_session: AsyncMock) -> None:
    app.dependency_overrides[get_session] = lambda: mock_db_session
    populated_summary = DashboardSummaryResult(
        hosts=HostsSummaryResult(total=12, enabled=10, disabled=2),
        scans=ScansSummaryResult(total=420, last_scan_at=_NOW),
        alerts=AlertsSummaryResult(
            total=40,
            by_status={"OPEN": 10, "ACKNOWLEDGED": 5, "RESOLVED": 25},
            by_severity={
                "INFO": 4,
                "LOW": 6,
                "MEDIUM": 8,
                "HIGH": 17,
                "CRITICAL": 5,
            },
        ),
    )

    try:
        with (
            patch.object(Settings, "get_api_key", return_value=None),
            patch(
                "app.services.dashboard_query.DashboardQueryService.get_summary",
                new_callable=AsyncMock,
                return_value=populated_summary,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/dashboard/summary")
                assert resp.status_code == 200
                data = resp.json()
                assert data["hosts"]["total"] == 12
                assert data["hosts"]["enabled"] == 10
                assert data["hosts"]["disabled"] == 2
                assert data["scans"]["total"] == 420
                assert data["scans"]["last_scan_at"] is not None
                assert data["alerts"]["total"] == 40
                assert data["alerts"]["by_status"]["OPEN"] == 10
                assert data["alerts"]["by_severity"]["CRITICAL"] == 5
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_dashboard_summary_auth(mock_db_session: AsyncMock) -> None:
    app.dependency_overrides[get_session] = lambda: mock_db_session
    empty_summary = DashboardSummaryResult(
        hosts=HostsSummaryResult(total=0, enabled=0, disabled=0),
        scans=ScansSummaryResult(total=0, last_scan_at=None),
        alerts=AlertsSummaryResult(
            total=0,
            by_status={s.value: 0 for s in AlertStatus},
            by_severity={s.name: 0 for s in Severity},
        ),
    )

    try:
        with (
            patch.object(Settings, "get_api_key", return_value="secret-api-key"),
            patch(
                "app.services.dashboard_query.DashboardQueryService.get_summary",
                new_callable=AsyncMock,
                return_value=empty_summary,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # Missing key -> 401
                resp = await client.get("/api/v1/dashboard/summary")
                assert resp.status_code == 401

                # Wrong key -> 401
                resp = await client.get(
                    "/api/v1/dashboard/summary",
                    headers={"X-API-Key": "wrong-key"},
                )
                assert resp.status_code == 401

                # Valid key -> 200
                resp = await client.get(
                    "/api/v1/dashboard/summary",
                    headers={"X-API-Key": "secret-api-key"},
                )
                assert resp.status_code == 200
    finally:
        app.dependency_overrides.clear()
