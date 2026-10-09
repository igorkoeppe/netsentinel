"""Unit tests for /api/v1/alerts endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_session
from app.core.config import Settings
from app.detection.alerts import (
    AlertStatus,
    AlertType,
    InvalidAlertStateTransitionError,
    Severity,
)
from app.main import app
from app.models.host import Host
from app.models.notification_delivery import NotificationDeliveryRecord
from app.models.security_alert import SecurityAlertRecord
from app.services.alert_query import AlertListItem
from app.services.alert_triage import AlertNotFoundError

_NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def mock_db_session() -> AsyncMock:
    return AsyncMock()


@pytest.mark.asyncio
async def test_alert_summary_endpoint(mock_db_session: AsyncMock) -> None:
    """GET /api/v1/alerts/summary aggregates metrics and is never
    confused with /{alert_id}.
    """
    app.dependency_overrides[get_session] = lambda: mock_db_session
    mock_summary = {
        "total": 12,
        "by_status": {"OPEN": 5, "ACKNOWLEDGED": 3, "RESOLVED": 4},
        "by_severity": {"INFO": 2, "LOW": 3, "MEDIUM": 4, "HIGH": 2, "CRITICAL": 1},
    }

    try:
        with (
            patch.object(Settings, "get_api_key", return_value=None),
            patch(
                "app.services.alert_query.AlertQueryService.get_summary",
                new_callable=AsyncMock,
                return_value=mock_summary,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/alerts/summary")
                assert resp.status_code == 200
                data = resp.json()
                assert data["total"] == 12
                assert data["by_status"]["OPEN"] == 5
                assert data["by_severity"]["CRITICAL"] == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_alerts_with_filters(mock_db_session: AsyncMock) -> None:
    """GET /api/v1/alerts parses status, severity, type, and target filters."""
    app.dependency_overrides[get_session] = lambda: mock_db_session
    sample_alerts = [
        AlertListItem(
            id=1,
            severity="high",
            alert_type="unexpected_open_port",
            status="OPEN",
            target="10.0.0.1",
            port=8080,
            created_at=_NOW,
        )
    ]

    try:
        with (
            patch.object(Settings, "get_api_key", return_value=None),
            patch(
                "app.services.alert_query.AlertQueryService.list_alerts",
                new_callable=AsyncMock,
                return_value=sample_alerts,
            ) as mock_list,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    "/api/v1/alerts?status=open&severity=high&type=UNEXPECTED_OPEN_PORT&target=10.0.0.1&limit=5&offset=0"
                )
                assert resp.status_code == 200
                data = resp.json()
                assert len(data["items"]) == 1
                item = data["items"][0]
                assert item["id"] == 1
                assert item["severity"] == "HIGH"
                assert item["status"] == "OPEN"
                assert item["alert_type"] == "UNEXPECTED_OPEN_PORT"
                assert item["target"] == "10.0.0.1"

                mock_list.assert_awaited_once_with(
                    limit=5,
                    offset=0,
                    status=AlertStatus.OPEN,
                    severity=Severity.HIGH,
                    alert_type=AlertType.UNEXPECTED_OPEN_PORT,
                    target="10.0.0.1",
                )
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_alerts_invalid_filters() -> None:
    with patch.object(Settings, "get_api_key", return_value=None):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Invalid status
            r_st = await client.get("/api/v1/alerts?status=INVALID_STATUS")
            assert r_st.status_code == 422

            # Invalid severity
            r_sv = await client.get("/api/v1/alerts?severity=SUPER_HIGH")
            assert r_sv.status_code == 422

            # Invalid type
            r_tp = await client.get("/api/v1/alerts?type=NONEXISTENT_TYPE")
            assert r_tp.status_code == 422

            # Limit > 100
            r_lim = await client.get("/api/v1/alerts?limit=101")
            assert r_lim.status_code == 422


@pytest.mark.asyncio
async def test_get_alert_details_all_states_and_not_found(
    mock_db_session: AsyncMock,
) -> None:
    app.dependency_overrides[get_session] = lambda: mock_db_session
    t_created = _NOW
    t_ack = _NOW + timedelta(minutes=5)
    t_res = _NOW + timedelta(minutes=10)

    alerts_by_id = {
        # 1. OPEN com port
        1: AlertListItem(
            id=1,
            severity="high",
            alert_type="unexpected_open_port",
            status="OPEN",
            target="10.0.0.1",
            port=8080,
            message="Port 8080 open",
            created_at=t_created,
            acknowledged_at=None,
            resolved_at=None,
        ),
        # 2. OPEN sem port
        2: AlertListItem(
            id=2,
            severity="critical",
            alert_type="host_down",
            status="OPEN",
            target="10.0.0.2",
            port=None,
            message="Host down",
            created_at=t_created,
            acknowledged_at=None,
            resolved_at=None,
        ),
        # 3. ACKNOWLEDGED
        3: AlertListItem(
            id=3,
            severity="medium",
            alert_type="unexpected_open_port",
            status="ACKNOWLEDGED",
            target="10.0.0.3",
            port=22,
            message="SSH port open",
            created_at=t_created,
            acknowledged_at=t_ack,
            resolved_at=None,
        ),
        # 4. RESOLVED após acknowledge
        4: AlertListItem(
            id=4,
            severity="low",
            alert_type="unexpected_open_port",
            status="RESOLVED",
            target="10.0.0.4",
            port=443,
            message="HTTPS port open",
            created_at=t_created,
            acknowledged_at=t_ack,
            resolved_at=t_res,
        ),
        # 5. RESOLVED diretamente com acknowledged_at=NULL
        5: AlertListItem(
            id=5,
            severity="info",
            alert_type="host_recovered",
            status="RESOLVED",
            target="10.0.0.5",
            port=None,
            message="Host recovered",
            created_at=t_created,
            acknowledged_at=None,
            resolved_at=t_res,
        ),
    }

    try:
        with (
            patch.object(Settings, "get_api_key", return_value=None),
            patch(
                "app.services.alert_query.AlertQueryService.get_alert",
                new_callable=AsyncMock,
                side_effect=lambda aid: alerts_by_id.get(aid),
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # 1. Alert OPEN com port -> details 200
                r1 = await client.get("/api/v1/alerts/1")
                assert r1.status_code == 200
                d1 = r1.json()
                assert d1["id"] == 1
                assert d1["alert_type"] == "UNEXPECTED_OPEN_PORT"
                assert d1["severity"] == "HIGH"
                assert d1["status"] == "OPEN"
                assert d1["target"] == "10.0.0.1"
                assert d1["port"] == 8080
                assert d1["message"] == "Port 8080 open"
                assert d1["created_at"] is not None
                assert d1["acknowledged_at"] is None
                assert d1["resolved_at"] is None

                # 2. Alert OPEN sem port -> details 200
                r2 = await client.get("/api/v1/alerts/2")
                assert r2.status_code == 200
                d2 = r2.json()
                assert d2["id"] == 2
                assert d2["status"] == "OPEN"
                assert d2["port"] is None
                assert d2["target"] == "10.0.0.2"

                # 3. Alert ACKNOWLEDGED -> details 200
                r3 = await client.get("/api/v1/alerts/3")
                assert r3.status_code == 200
                d3 = r3.json()
                assert d3["id"] == 3
                assert d3["status"] == "ACKNOWLEDGED"
                assert d3["acknowledged_at"] is not None
                assert d3["resolved_at"] is None

                # 4. Alert RESOLVED após acknowledge -> details 200
                r4 = await client.get("/api/v1/alerts/4")
                assert r4.status_code == 200
                d4 = r4.json()
                assert d4["id"] == 4
                assert d4["status"] == "RESOLVED"
                assert d4["acknowledged_at"] is not None
                assert d4["resolved_at"] is not None

                # 5. Alert RESOLVED diretamente com acknowledged_at=NULL -> details 200
                r5 = await client.get("/api/v1/alerts/5")
                assert r5.status_code == 200
                d5 = r5.json()
                assert d5["id"] == 5
                assert d5["status"] == "RESOLVED"
                assert d5["acknowledged_at"] is None
                assert d5["resolved_at"] is not None

                # Nonexistent -> 404
                resp_nf = await client.get("/api/v1/alerts/999999")
                assert resp_nf.status_code == 404
                assert resp_nf.json()["error"]["code"] == "ALERT_NOT_FOUND"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_alert_deliveries(mock_db_session: AsyncMock) -> None:
    app.dependency_overrides[get_session] = lambda: mock_db_session
    mock_alert = AlertListItem(
        id=10,
        severity="high",
        alert_type="unexpected_open_port",
        status="OPEN",
        target="10.0.0.1",
        port=80,
        created_at=_NOW,
    )

    delivery1 = NotificationDeliveryRecord(
        id=1,
        alert_id=10,
        channel="webhook",
        notification_id="notif-1",
        success=True,
        delivered_at=_NOW,
        error_message=None,
        created_at=_NOW,
    )

    try:
        with (
            patch.object(Settings, "get_api_key", return_value=None),
            patch(
                "app.services.alert_query.AlertQueryService.get_alert",
                new_callable=AsyncMock,
                side_effect=lambda aid: mock_alert if aid == 10 else None,
            ),
            patch(
                "app.repositories.notification_delivery.NotificationDeliveryRepository.list_by_alert",
                new_callable=AsyncMock,
                return_value=[delivery1],
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # Existing alert with delivery
                resp = await client.get("/api/v1/alerts/10/deliveries")
                assert resp.status_code == 200
                data = resp.json()
                assert len(data["items"]) == 1
                deliv = data["items"][0]
                assert deliv["id"] == 1
                assert deliv["channel"] == "webhook"
                assert deliv["success"] is True
                assert deliv["error"] is None

                # Nonexistent alert -> 404
                resp_nf = await client.get("/api/v1/alerts/99/deliveries")
                assert resp_nf.status_code == 404
                assert resp_nf.json()["error"]["code"] == "ALERT_NOT_FOUND"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_acknowledge_and_resolve_transitions(mock_db_session: AsyncMock) -> None:
    app.dependency_overrides[get_session] = lambda: mock_db_session
    mock_host = MagicMock(spec=Host)
    mock_host.address = "127.0.0.1"

    ack_record = MagicMock(spec=SecurityAlertRecord)
    ack_record.id = 5
    ack_record.alert_type = "unexpected_open_port"
    ack_record.severity = "high"
    ack_record.status = "ACKNOWLEDGED"
    ack_record.host = mock_host
    ack_record.port = 8080
    ack_record.message = "Port opened"
    ack_record.created_at = _NOW
    ack_record.acknowledged_at = _NOW
    ack_record.resolved_at = None

    try:
        with (
            patch.object(Settings, "get_api_key", return_value="mutation-key"),
            patch(
                "app.services.alert_triage.AlertTriageService.acknowledge",
                new_callable=AsyncMock,
                return_value=ack_record,
            ),
            patch(
                "app.services.alert_triage.AlertTriageService.resolve",
                new_callable=AsyncMock,
                return_value=ack_record,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                headers = {"X-API-Key": "mutation-key"}

                # Successful acknowledge
                resp_ack = await client.post(
                    "/api/v1/alerts/5/acknowledge", headers=headers
                )
                assert resp_ack.status_code == 200
                assert resp_ack.json()["status"] == "ACKNOWLEDGED"

                # Successful resolve
                resp_res = await client.post(
                    "/api/v1/alerts/5/resolve", headers=headers
                )
                assert resp_res.status_code == 200
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_triage_errors(mock_db_session: AsyncMock) -> None:
    app.dependency_overrides[get_session] = lambda: mock_db_session
    try:
        with patch.object(Settings, "get_api_key", return_value="mutation-key"):
            headers = {"X-API-Key": "mutation-key"}
            # 1. Alert not found -> 404
            with patch(
                "app.services.alert_triage.AlertTriageService.acknowledge",
                new_callable=AsyncMock,
                side_effect=AlertNotFoundError(404),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/v1/alerts/404/acknowledge", headers=headers
                    )
                    assert resp.status_code == 404
                    assert resp.json()["error"]["code"] == "ALERT_NOT_FOUND"

            # 2. Invalid state transition -> 409
            with patch(
                "app.services.alert_triage.AlertTriageService.acknowledge",
                new_callable=AsyncMock,
                side_effect=InvalidAlertStateTransitionError(
                    AlertStatus.RESOLVED, AlertStatus.ACKNOWLEDGED
                ),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp_conflict = await client.post(
                        "/api/v1/alerts/5/acknowledge", headers=headers
                    )
                    assert resp_conflict.status_code == 409
                    assert resp_conflict.json()["error"]["code"] == "INVALID_TRANSITION"
    finally:
        app.dependency_overrides.clear()
