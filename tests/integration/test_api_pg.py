"""PostgreSQL Integration tests for NetSentinel REST API endpoints.

Requires ``TEST_DATABASE_URL`` to be set and is tagged with the ``integration`` marker.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.core.config import Settings
from app.detection.alerts import AlertStatus, AlertType, SecurityAlert, Severity
from app.detection.engine import MonitoringEvent, MonitoringEventType
from app.main import app
from app.monitoring.target import NetworkTarget
from app.repositories.alert import AlertRepository
from app.repositories.host import HostRepository
from app.repositories.monitoring_event import MonitoringEventRepository
from app.repositories.notification_delivery import NotificationDeliveryRepository
from app.repositories.scan import PortResultInput, ScanRepository

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)
_TARGET = NetworkTarget.parse("192.168.1.100")
_API_KEY = "test-integration-secret-key"


@pytest.fixture(autouse=True)
async def cleanup_db(pg_session: AsyncSession) -> AsyncGenerator[None, None]:
    """Clean up database tables before and after each test."""
    await pg_session.execute(text("TRUNCATE TABLE notification_deliveries CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE security_alerts CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE monitoring_events CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE port_results CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE scans CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE hosts CASCADE"))
    await pg_session.commit()
    yield
    await pg_session.execute(text("TRUNCATE TABLE notification_deliveries CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE security_alerts CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE monitoring_events CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE port_results CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE scans CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE hosts CASCADE"))
    await pg_session.commit()


@pytest.fixture
def override_api_deps(pg_session: AsyncSession):
    app.dependency_overrides[get_session] = lambda: pg_session
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_hosts_and_history_pg(
    pg_session: AsyncSession, override_api_deps: None
) -> None:
    host_repo = HostRepository(pg_session)
    scan_repo = ScanRepository(pg_session)

    host = await host_repo.get_or_create(address=_TARGET.value)
    await pg_session.commit()

    await scan_repo.create(
        host_id=host.id,
        status="available",
        response_time_ms=5.2,
        started_at=_NOW,
        finished_at=_NOW,
    )
    await pg_session.commit()

    with patch.object(Settings, "get_api_key", return_value=None):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # 1. List hosts
            resp = await client.get("/api/v1/hosts")
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 1
            assert len(data["items"]) == 1
            assert data["items"][0]["address"] == _TARGET.value

            # 2. Host history
            resp_hist = await client.get(f"/api/v1/hosts/{_TARGET.value}/history")
            assert resp_hist.status_code == 200
            hist_data = resp_hist.json()
            assert hist_data["address"] == _TARGET.value
            assert len(hist_data["scans"]) == 1
            assert hist_data["scans"][0]["status"] == "available"


@pytest.mark.asyncio
async def test_api_scans_details_pg(
    pg_session: AsyncSession, override_api_deps: None
) -> None:
    host_repo = HostRepository(pg_session)
    scan_repo = ScanRepository(pg_session)
    event_repo = MonitoringEventRepository(pg_session)
    alert_repo = AlertRepository(pg_session)

    host = await host_repo.get_or_create(address=_TARGET.value)
    await pg_session.commit()

    scan = await scan_repo.create(
        host_id=host.id,
        status="available",
        response_time_ms=10.0,
        started_at=_NOW,
        finished_at=_NOW,
    )
    await scan_repo.add_port_results(
        scan_id=scan.id,
        results=[PortResultInput(port=80, status="open", response_time_ms=2.5)],
    )
    await pg_session.commit()

    evt = MonitoringEvent(
        event_type=MonitoringEventType.PORT_OPENED,
        target=_TARGET,
        port=80,
        previous_state="closed",
        current_state="open",
        timestamp=_NOW,
    )
    saved_evt = await event_repo.create(host_id=host.id, scan_id=scan.id, event=evt)
    await pg_session.commit()

    alert = SecurityAlert(
        target=_TARGET,
        port=80,
        alert_type=AlertType.UNEXPECTED_OPEN_PORT,
        severity=Severity.HIGH,
        message="Port 80 is unexpectedly open",
        timestamp=_NOW,
        source_event_type=saved_evt.event_type,
    )
    await alert_repo.create(
        host_id=host.id,
        scan_id=scan.id,
        monitoring_event_id=saved_evt.id,
        alert=alert,
    )
    await pg_session.commit()

    with patch.object(Settings, "get_api_key", return_value=None):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/v1/scans/{scan.id}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["id"] == scan.id
            assert data["target"] == _TARGET.value
            assert data["status"] == "AVAILABLE"
            assert len(data["ports"]) == 1
            assert data["ports"][0]["port"] == 80
            assert data["ports"][0]["status"] == "OPEN"
            assert len(data["events"]) == 1
            assert data["events"][0]["event_type"] == "PORT_OPENED"
            assert len(data["alerts"]) == 1
            assert data["alerts"][0]["severity"] == "HIGH"


@pytest.mark.asyncio
async def test_api_alerts_summary_and_filtering_pg(
    pg_session: AsyncSession, override_api_deps: None
) -> None:
    host_repo = HostRepository(pg_session)
    alert_repo = AlertRepository(pg_session)

    host1 = await host_repo.create(address="10.0.0.1")
    host2 = await host_repo.create(address="10.0.0.2")

    alert1 = SecurityAlert(
        target=NetworkTarget.parse("10.0.0.1"),
        port=22,
        alert_type=AlertType.NEW_OPEN_PORT,
        severity=Severity.CRITICAL,
        message="Port 22 SSH opened",
        timestamp=_NOW,
        source_event_type="port_opened",
    )
    alert2 = SecurityAlert(
        target=NetworkTarget.parse("10.0.0.2"),
        port=80,
        alert_type=AlertType.PORT_CLOSED,
        severity=Severity.MEDIUM,
        message="Port 80 closed",
        timestamp=_NOW,
        source_event_type="port_closed",
    )

    rec1 = await alert_repo.create(
        host_id=host1.id, scan_id=None, monitoring_event_id=None, alert=alert1
    )
    rec2 = await alert_repo.create(
        host_id=host2.id, scan_id=None, monitoring_event_id=None, alert=alert2
    )
    # Acknowledge rec2
    rec2.status = AlertStatus.ACKNOWLEDGED.value
    await pg_session.commit()

    with patch.object(Settings, "get_api_key", return_value=None):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # 1. Summary
            resp_sum = await client.get("/api/v1/alerts/summary")
            assert resp_sum.status_code == 200
            sum_data = resp_sum.json()
            assert sum_data["total"] == 2
            assert sum_data["by_status"]["OPEN"] == 1
            assert sum_data["by_status"]["ACKNOWLEDGED"] == 1
            assert sum_data["by_status"]["RESOLVED"] == 0
            assert sum_data["by_severity"]["CRITICAL"] == 1
            assert sum_data["by_severity"]["MEDIUM"] == 1
            assert sum_data["by_severity"]["INFO"] == 0

            # 2. Filter by status=OPEN
            resp_f1 = await client.get("/api/v1/alerts?status=OPEN")
            assert resp_f1.status_code == 200
            assert len(resp_f1.json()["items"]) == 1
            assert resp_f1.json()["items"][0]["id"] == rec1.id

            # 3. Filter by target=10.0.0.2
            resp_f2 = await client.get("/api/v1/alerts?target=10.0.0.2")
            assert resp_f2.status_code == 200
            assert len(resp_f2.json()["items"]) == 1
            assert resp_f2.json()["items"][0]["id"] == rec2.id


@pytest.mark.asyncio
async def test_api_alert_deliveries_pg(
    pg_session: AsyncSession, override_api_deps: None
) -> None:
    host_repo = HostRepository(pg_session)
    alert_repo = AlertRepository(pg_session)
    delivery_repo = NotificationDeliveryRepository(pg_session)

    host = await host_repo.create(address="10.0.0.1")
    alert = SecurityAlert(
        target=NetworkTarget.parse("10.0.0.1"),
        port=443,
        alert_type=AlertType.NEW_OPEN_PORT,
        severity=Severity.LOW,
        message="Port 443 open",
        timestamp=_NOW,
        source_event_type="port_opened",
    )
    saved = await alert_repo.create(
        host_id=host.id, scan_id=None, monitoring_event_id=None, alert=alert
    )
    await pg_session.commit()

    await delivery_repo.create(
        alert_id=saved.id,
        channel="webhook",
        notification_id="webhook-id-123",
        success=True,
        error_message=None,
        delivered_at=_NOW,
    )
    await pg_session.commit()

    with patch.object(Settings, "get_api_key", return_value=None):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/v1/alerts/{saved.id}/deliveries")
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 1
            assert len(data["items"]) == 1
            assert data["items"][0]["channel"] == "webhook"
            assert data["items"][0]["success"] is True


@pytest.mark.asyncio
async def test_api_alert_triage_e2e_lifecycle_pg(
    pg_session: AsyncSession, override_api_deps: None
) -> None:
    """E2E test: OPEN -> ACKNOWLEDGE -> RESOLVE -> Invalid transition (409)."""
    host_repo = HostRepository(pg_session)
    alert_repo = AlertRepository(pg_session)

    host = await host_repo.create(address="192.168.1.50")
    alert = SecurityAlert(
        target=NetworkTarget.parse("192.168.1.50"),
        port=8080,
        alert_type=AlertType.UNEXPECTED_OPEN_PORT,
        severity=Severity.HIGH,
        message="Unapproved service on 8080",
        timestamp=_NOW,
        source_event_type="port_opened",
    )
    saved = await alert_repo.create(
        host_id=host.id, scan_id=None, monitoring_event_id=None, alert=alert
    )
    await pg_session.commit()

    with patch.object(Settings, "get_api_key", return_value=_API_KEY):
        headers = {"X-API-Key": _API_KEY}
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # 1. Verify initial status is OPEN
            resp_get = await client.get(f"/api/v1/alerts/{saved.id}", headers=headers)
            assert resp_get.status_code == 200
            assert resp_get.json()["status"] == "OPEN"

            # 2. Acknowledge
            resp_ack = await client.post(
                f"/api/v1/alerts/{saved.id}/acknowledge", headers=headers
            )
            assert resp_ack.status_code == 200
            ack_data = resp_ack.json()
            assert ack_data["status"] == "ACKNOWLEDGED"
            assert ack_data["acknowledged_at"] is not None

            # 3. Resolve
            resp_res = await client.post(
                f"/api/v1/alerts/{saved.id}/resolve", headers=headers
            )
            assert resp_res.status_code == 200
            res_data = resp_res.json()
            assert res_data["status"] == "RESOLVED"
            assert res_data["resolved_at"] is not None

            # 4. Attempt invalid transition: RESOLVED -> ACKNOWLEDGE -> 409 Conflict
            resp_inv = await client.post(
                f"/api/v1/alerts/{saved.id}/acknowledge", headers=headers
            )
            assert resp_inv.status_code == 409
            inv_data = resp_inv.json()
            assert inv_data["error"]["code"] == "INVALID_TRANSITION"
            assert "Cannot transition alert" in inv_data["error"]["message"]
