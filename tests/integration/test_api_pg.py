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


@pytest.mark.asyncio
async def test_hosts_q_search_pg(
    pg_session: AsyncSession, override_api_deps: None
) -> None:
    host_repo = HostRepository(pg_session)
    await host_repo.create(address="10.0.0.1", name="Alpha Server")
    h2 = await host_repo.create(address="10.0.0.2", name="Beta Node")
    await host_repo.update(h2, enabled=False)
    await host_repo.create(address="192.168.1.50", name="Gamma Gateway")
    await pg_session.commit()

    with patch.object(Settings, "get_api_key", return_value=_API_KEY):
        headers = {"X-API-Key": _API_KEY}
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Search by name substring
            resp = await client.get("/api/v1/hosts?q=beta", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 1
            assert data["items"][0]["name"] == "Beta Node"

            # Search by address substring
            resp2 = await client.get("/api/v1/hosts?q=192.168", headers=headers)
            assert resp2.status_code == 200
            assert resp2.json()["count"] == 1
            assert resp2.json()["items"][0]["address"] == "192.168.1.50"

            # Combined with enabled filter
            resp3 = await client.get(
                "/api/v1/hosts?q=0.0&enabled=true", headers=headers
            )
            assert resp3.status_code == 200
            assert resp3.json()["count"] == 1
            assert resp3.json()["items"][0]["name"] == "Alpha Server"


@pytest.mark.asyncio
async def test_scans_global_list_pg(
    pg_session: AsyncSession, override_api_deps: None
) -> None:
    host_repo = HostRepository(pg_session)
    h1 = await host_repo.create(address="10.1.1.1", name="Host 1")
    h2 = await host_repo.create(address="10.1.1.2", name="Host 2")
    scan_repo = ScanRepository(pg_session)

    s1 = await scan_repo.create(
        host_id=h1.id,
        status="available",
        response_time_ms=1.2,
        started_at=_NOW,
        finished_at=_NOW,
    )
    s2 = await scan_repo.create(
        host_id=h2.id,
        status="unavailable",
        response_time_ms=None,
        started_at=_NOW,
        finished_at=_NOW,
    )
    await pg_session.commit()

    with patch.object(Settings, "get_api_key", return_value=_API_KEY):
        headers = {"X-API-Key": _API_KEY}
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Global list all
            resp = await client.get("/api/v1/scans", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 2
            ids = [item["id"] for item in data["items"]]
            assert s1.id in ids
            assert s2.id in ids

            # Filter by target
            resp_target = await client.get(
                "/api/v1/scans?target=10.1.1.1", headers=headers
            )
            assert resp_target.status_code == 200
            assert resp_target.json()["count"] == 1
            assert resp_target.json()["items"][0]["target"] == "10.1.1.1"

            # Filter by non-existent target
            resp_none = await client.get(
                "/api/v1/scans?target=192.168.99.99", headers=headers
            )
            assert resp_none.status_code == 200
            assert resp_none.json()["count"] == 0


@pytest.mark.asyncio
async def test_dashboard_summary_pg(
    pg_session: AsyncSession, override_api_deps: None
) -> None:
    host_repo = HostRepository(pg_session)
    h1 = await host_repo.create(address="172.16.0.1", name="H1")
    h2 = await host_repo.create(address="172.16.0.2", name="H2")
    await host_repo.update(h2, enabled=False)

    scan_repo = ScanRepository(pg_session)
    await scan_repo.create(
        host_id=h1.id,
        status="available",
        response_time_ms=2.0,
        started_at=_NOW,
        finished_at=_NOW,
    )

    alert_repo = AlertRepository(pg_session)
    alert = SecurityAlert(
        target=NetworkTarget.parse("172.16.0.1"),
        port=22,
        alert_type=AlertType.NEW_OPEN_PORT,
        severity=Severity.CRITICAL,
        message="Critical port 22 open",
        timestamp=_NOW,
        source_event_type="port_opened",
    )
    await alert_repo.create(
        host_id=h1.id, scan_id=None, monitoring_event_id=None, alert=alert
    )
    await pg_session.commit()

    with patch.object(Settings, "get_api_key", return_value=_API_KEY):
        headers = {"X-API-Key": _API_KEY}
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/dashboard/summary", headers=headers)
            assert resp.status_code == 200
            data = resp.json()

            # Verify hosts breakdown
            assert data["hosts"]["total"] == 2
            assert data["hosts"]["enabled"] == 1
            assert data["hosts"]["disabled"] == 1

            # Verify scans metrics
            assert data["scans"]["total"] == 1
            assert data["scans"]["last_scan_at"] is not None

            # Verify alerts breakdown
            assert data["alerts"]["total"] == 1
            assert data["alerts"]["by_status"]["OPEN"] == 1
            assert data["alerts"]["by_status"]["RESOLVED"] == 0
            assert data["alerts"]["by_severity"]["CRITICAL"] == 1
            assert data["alerts"]["by_severity"]["INFO"] == 0


@pytest.mark.asyncio
async def test_api_alert_details_all_states_and_no_missing_greenlet_pg(
    pg_session: AsyncSession, override_api_deps: None
) -> None:
    """Validate alert details across all states, ensuring eager load
    prevents MissingGreenlet.
    """
    host_repo = HostRepository(pg_session)
    alert_repo = AlertRepository(pg_session)
    delivery_repo = NotificationDeliveryRepository(pg_session)

    host = await host_repo.create(address="10.99.1.1", name="Target Host")

    # 1. Alert OPEN com port
    alert_open_port = SecurityAlert(
        target=NetworkTarget.parse("10.99.1.1"),
        port=8080,
        alert_type=AlertType.UNEXPECTED_OPEN_PORT,
        severity=Severity.HIGH,
        message="Port 8080 open unexpectedly",
        timestamp=_NOW,
        source_event_type="port_opened",
    )
    rec_open_port = await alert_repo.create(
        host_id=host.id, scan_id=None, monitoring_event_id=None, alert=alert_open_port
    )

    # 2. Alert OPEN sem port
    alert_open_no_port = SecurityAlert(
        target=NetworkTarget.parse("10.99.1.1"),
        port=None,
        alert_type=AlertType.HOST_DOWN,
        severity=Severity.CRITICAL,
        message="Host became unreachable",
        timestamp=_NOW,
        source_event_type="host_became_unavailable",
    )
    rec_open_no_port = await alert_repo.create(
        host_id=host.id,
        scan_id=None,
        monitoring_event_id=None,
        alert=alert_open_no_port,
    )

    # 3. Alert ACKNOWLEDGED
    t_ack = datetime(2026, 10, 4, 12, 10, 0, tzinfo=UTC)
    alert_ack = SecurityAlert(
        target=NetworkTarget.parse("10.99.1.1"),
        port=22,
        alert_type=AlertType.NEW_OPEN_PORT,
        severity=Severity.MEDIUM,
        message="Port 22 SSH open",
        timestamp=_NOW,
        source_event_type="port_opened",
    )
    rec_ack = await alert_repo.create(
        host_id=host.id, scan_id=None, monitoring_event_id=None, alert=alert_ack
    )
    rec_ack.status = AlertStatus.ACKNOWLEDGED.value
    rec_ack.acknowledged_at = t_ack

    # 4. Alert RESOLVED apos acknowledge
    t_res1 = datetime(2026, 10, 4, 12, 20, 0, tzinfo=UTC)
    alert_res1 = SecurityAlert(
        target=NetworkTarget.parse("10.99.1.1"),
        port=443,
        alert_type=AlertType.NEW_OPEN_PORT,
        severity=Severity.LOW,
        message="Port 443 HTTPS open",
        timestamp=_NOW,
        source_event_type="port_opened",
    )
    rec_res1 = await alert_repo.create(
        host_id=host.id, scan_id=None, monitoring_event_id=None, alert=alert_res1
    )
    rec_res1.status = AlertStatus.RESOLVED.value
    rec_res1.acknowledged_at = t_ack
    rec_res1.resolved_at = t_res1

    # 5. Alert RESOLVED diretamente com acknowledged_at=NULL
    t_res2 = datetime(2026, 10, 4, 12, 15, 0, tzinfo=UTC)
    alert_res2 = SecurityAlert(
        target=NetworkTarget.parse("10.99.1.1"),
        port=None,
        alert_type=AlertType.HOST_RECOVERED,
        severity=Severity.INFO,
        message="Host recovered",
        timestamp=_NOW,
        source_event_type="host_became_available",
    )
    rec_res2 = await alert_repo.create(
        host_id=host.id, scan_id=None, monitoring_event_id=None, alert=alert_res2
    )
    rec_res2.status = AlertStatus.RESOLVED.value
    rec_res2.acknowledged_at = None
    rec_res2.resolved_at = t_res2

    await pg_session.commit()

    # Create delivery for rec_open_port
    await delivery_repo.create(
        alert_id=rec_open_port.id,
        channel="webhook",
        notification_id="delivery-test-1",
        success=True,
        error_message=None,
        delivered_at=_NOW,
    )
    await pg_session.commit()

    # Expunge all objects to guarantee identity map is empty and test eager loading
    pg_session.expunge_all()

    with patch.object(Settings, "get_api_key", return_value=_API_KEY):
        headers = {"X-API-Key": _API_KEY}
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # 1. Alert OPEN com port -> 200
            resp1 = await client.get(
                f"/api/v1/alerts/{rec_open_port.id}", headers=headers
            )
            assert resp1.status_code == 200
            d1 = resp1.json()
            assert d1["id"] == rec_open_port.id
            assert d1["alert_type"] == "UNEXPECTED_OPEN_PORT"
            assert d1["status"] == "OPEN"
            assert d1["port"] == 8080
            assert d1["target"] == "10.99.1.1"
            assert d1["severity"] == "HIGH"
            assert d1["message"] == "Port 8080 open unexpectedly"
            assert d1["created_at"] is not None
            assert d1["acknowledged_at"] is None
            assert d1["resolved_at"] is None

            # 2. Alert OPEN sem port -> 200
            resp2 = await client.get(
                f"/api/v1/alerts/{rec_open_no_port.id}", headers=headers
            )
            assert resp2.status_code == 200
            d2 = resp2.json()
            assert d2["id"] == rec_open_no_port.id
            assert d2["status"] == "OPEN"
            assert d2["port"] is None
            assert d2["target"] == "10.99.1.1"

            # 3. Alert ACKNOWLEDGED -> 200
            resp3 = await client.get(f"/api/v1/alerts/{rec_ack.id}", headers=headers)
            assert resp3.status_code == 200
            d3 = resp3.json()
            assert d3["id"] == rec_ack.id
            assert d3["status"] == "ACKNOWLEDGED"
            assert d3["acknowledged_at"] is not None
            assert d3["resolved_at"] is None

            # 4. Alert RESOLVED apos acknowledge -> 200
            resp4 = await client.get(f"/api/v1/alerts/{rec_res1.id}", headers=headers)
            assert resp4.status_code == 200
            d4 = resp4.json()
            assert d4["id"] == rec_res1.id
            assert d4["status"] == "RESOLVED"
            assert d4["acknowledged_at"] is not None
            assert d4["resolved_at"] is not None

            # 5. Alert RESOLVED diretamente com acknowledged_at=NULL -> 200
            resp5 = await client.get(f"/api/v1/alerts/{rec_res2.id}", headers=headers)
            assert resp5.status_code == 200
            d5 = resp5.json()
            assert d5["id"] == rec_res2.id
            assert d5["status"] == "RESOLVED"
            assert d5["acknowledged_at"] is None
            assert d5["resolved_at"] is not None

            # 6. Inexistente -> 404
            resp_nf = await client.get("/api/v1/alerts/999999", headers=headers)
            assert resp_nf.status_code == 404
            assert resp_nf.json()["error"]["code"] == "ALERT_NOT_FOUND"

            # 7. List endpoint continua funcionando
            resp_list = await client.get(
                "/api/v1/alerts?target=10.99.1.1", headers=headers
            )
            assert resp_list.status_code == 200
            assert resp_list.json()["count"] == 5

            # 8. Deliveries continuam funcionando
            resp_deliv = await client.get(
                f"/api/v1/alerts/{rec_open_port.id}/deliveries", headers=headers
            )
            assert resp_deliv.status_code == 200
            assert resp_deliv.json()["count"] == 1
            assert resp_deliv.json()["items"][0]["channel"] == "webhook"

            # 9. Acknowledge continua funcionando
            resp_ack_mut = await client.post(
                f"/api/v1/alerts/{rec_open_no_port.id}/acknowledge", headers=headers
            )
            assert resp_ack_mut.status_code == 200
            assert resp_ack_mut.json()["status"] == "ACKNOWLEDGED"

            # 10. Resolve continua funcionando
            resp_res_mut = await client.post(
                f"/api/v1/alerts/{rec_open_no_port.id}/resolve", headers=headers
            )
            assert resp_res_mut.status_code == 200
            assert resp_res_mut.json()["status"] == "RESOLVED"
