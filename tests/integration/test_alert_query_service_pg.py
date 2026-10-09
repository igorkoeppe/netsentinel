"""Integration tests for AlertQueryService against PostgreSQL.

These tests require ``TEST_DATABASE_URL`` to be set and are tagged with the
``integration`` marker.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.detection.alerts import (
    AlertStatus,
    AlertType,
    SecurityAlert,
    Severity,
    acknowledge_alert,
    resolve_alert,
)
from app.monitoring.target import NetworkTarget
from app.repositories.alert import AlertRepository
from app.repositories.host import HostRepository
from app.services.alert_query import AlertQueryService

pytestmark = pytest.mark.integration

_BASE_TIME = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _make_alert(
    *,
    target_str: str = "10.0.0.1",
    port: int | None = 80,
    alert_type: AlertType = AlertType.NEW_OPEN_PORT,
    severity: Severity = Severity.HIGH,
    timestamp: datetime = _BASE_TIME,
) -> SecurityAlert:
    return SecurityAlert(
        target=NetworkTarget.parse(target_str),
        port=port,
        alert_type=alert_type,
        severity=severity,
        message=f"Test alert for port {port}",
        timestamp=timestamp,
        source_event_type="port_opened" if port else "host_down",
    )


@pytest.fixture(autouse=True)
async def cleanup_db(pg_session: AsyncSession) -> None:
    """Clean up tables before and after each integration test."""
    await pg_session.execute(text("TRUNCATE TABLE security_alerts CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE monitoring_events CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE port_results CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE scans CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE hosts CASCADE"))
    await pg_session.commit()
    yield
    await pg_session.execute(text("TRUNCATE TABLE security_alerts CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE monitoring_events CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE port_results CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE scans CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE hosts CASCADE"))
    await pg_session.commit()


@pytest.fixture
async def query_service(pg_session: AsyncSession) -> AlertQueryService:
    return AlertQueryService(pg_session)


class TestAlertQueryServicePG:
    async def test_list_alerts_statuses_targets_and_ordering(
        self,
        query_service: AlertQueryService,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        """Confirm 3 alerts with OPEN, ACKNOWLEDGED, RESOLVED statuses.

        Also verifies correct targets and ordering.
        """
        alert_repo = AlertRepository(pg_session)

        # Host 1
        host1 = await host_repo.create(address="192.168.1.10")
        # Host 2
        host2 = await host_repo.create(address="10.0.0.5")

        # Alert A (oldest, OPEN)
        alert_a = await alert_repo.create(
            host_id=host1.id,
            scan_id=None,
            monitoring_event_id=None,
            alert=_make_alert(
                target_str="192.168.1.10",
                port=80,
                alert_type=AlertType.NEW_OPEN_PORT,
                severity=Severity.HIGH,
                timestamp=_BASE_TIME,
            ),
        )

        # Alert B (middle, ACKNOWLEDGED)
        ack_time = _BASE_TIME + timedelta(minutes=10)
        alert_b = await alert_repo.create(
            host_id=host2.id,
            scan_id=None,
            monitoring_event_id=None,
            alert=_make_alert(
                target_str="10.0.0.5",
                port=443,
                alert_type=AlertType.UNEXPECTED_OPEN_PORT,
                severity=Severity.CRITICAL,
                timestamp=_BASE_TIME + timedelta(minutes=5),
            ),
        )
        b_lifecycle = acknowledge_alert(alert_b.to_lifecycle(), at=ack_time)
        await alert_repo.update_lifecycle(alert_b.id, b_lifecycle)

        # Alert C (newest, RESOLVED)
        res_time = _BASE_TIME + timedelta(minutes=30)
        alert_c = await alert_repo.create(
            host_id=host1.id,
            scan_id=None,
            monitoring_event_id=None,
            alert=_make_alert(
                target_str="192.168.1.10",
                port=None,
                alert_type=AlertType.HOST_DOWN,
                severity=Severity.MEDIUM,
                timestamp=_BASE_TIME + timedelta(minutes=20),
            ),
        )
        c_lifecycle = resolve_alert(alert_c.to_lifecycle(), at=res_time)
        await alert_repo.update_lifecycle(alert_c.id, c_lifecycle)

        await pg_session.commit()

        # Query via service
        items = await query_service.list_alerts(limit=20)

        # Must have 3 items ordered newest first (C, B, A)
        assert len(items) == 3
        assert [item.id for item in items] == [alert_c.id, alert_b.id, alert_a.id]

        # Item C details
        item_c = items[0]
        assert item_c.id == alert_c.id
        assert item_c.status == "RESOLVED"
        assert item_c.target == "192.168.1.10"
        assert item_c.severity == "medium"
        assert item_c.alert_type == "host_down"
        assert item_c.port is None
        assert item_c.resolved_at == res_time

        # Item B details
        item_b = items[1]
        assert item_b.id == alert_b.id
        assert item_b.status == "ACKNOWLEDGED"
        assert item_b.target == "10.0.0.5"
        assert item_b.severity == "critical"
        assert item_b.alert_type == "unexpected_open_port"
        assert item_b.port == 443
        assert item_b.acknowledged_at == ack_time

        # Item A details
        item_a = items[2]
        assert item_a.id == alert_a.id
        assert item_a.status == "OPEN"
        assert item_a.target == "192.168.1.10"
        assert item_a.severity == "high"
        assert item_a.alert_type == "new_open_port"
        assert item_a.port == 80
        assert item_a.acknowledged_at is None
        assert item_a.resolved_at is None

    async def test_list_alerts_limit(
        self,
        query_service: AlertQueryService,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        """Confirm limit restricts the number of returned alerts."""
        alert_repo = AlertRepository(pg_session)
        host = await host_repo.create(address="127.0.0.1")

        created_ids = []
        for i in range(5):
            rec = await alert_repo.create(
                host_id=host.id,
                scan_id=None,
                monitoring_event_id=None,
                alert=_make_alert(
                    target_str="127.0.0.1",
                    port=8000 + i,
                    timestamp=_BASE_TIME + timedelta(minutes=i),
                ),
            )
            created_ids.append(rec.id)

        await pg_session.commit()

        # Query with limit=2
        items = await query_service.list_alerts(limit=2)

        assert len(items) == 2
        # Most recent first: index 4 and 3
        assert items[0].id == created_ids[4]
        assert items[1].id == created_ids[3]

    async def test_get_alert_persisted(
        self,
        query_service: AlertQueryService,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        alert_repo = AlertRepository(pg_session)
        host = await host_repo.create(address="10.20.30.40")
        rec = await alert_repo.create(
            host_id=host.id,
            scan_id=None,
            monitoring_event_id=None,
            alert=_make_alert(
                target_str="10.20.30.40",
                port=22,
                alert_type=AlertType.NEW_OPEN_PORT,
                severity=Severity.HIGH,
                timestamp=_BASE_TIME,
            ),
        )
        await pg_session.commit()
        # Expire session to ensure entity is not cached and lazy-loading would fail
        pg_session.expire_all()

        item = await query_service.get_alert(rec.id)
        assert item is not None
        assert item.id == rec.id
        assert item.target == "10.20.30.40"
        assert item.port == 22
        assert item.status == "OPEN"

        # Nonexistent alert
        not_found = await query_service.get_alert(999_999)
        assert not_found is None

    async def test_eager_loading_no_n_plus_one(
        self,
        query_service: AlertQueryService,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        """Confirm joinedload eagerly loads host data.

        Ensures detached records retain target address without extra queries.
        """
        alert_repo = AlertRepository(pg_session)
        host = await host_repo.create(address="10.99.0.1")
        for i in range(3):
            await alert_repo.create(
                host_id=host.id,
                scan_id=None,
                monitoring_event_id=None,
                alert=_make_alert(
                    target_str="10.99.0.1",
                    port=9000 + i,
                    timestamp=_BASE_TIME + timedelta(minutes=i),
                ),
            )
        await pg_session.commit()

        # Expire session to detach records and ensure no cache
        pg_session.expire_all()

        items = await query_service.list_alerts(limit=10)
        assert len(items) == 3
        for item in items:
            assert item.target == "10.99.0.1"

    async def test_list_alerts_filtered_by_status_and_severity(
        self,
        query_service: AlertQueryService,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        """Verify status and severity filters in PostgreSQL.

        Creates 5 alerts:
        1. OPEN / HIGH
        2. OPEN / LOW
        3. ACKNOWLEDGED / HIGH
        4. RESOLVED / HIGH
        5. RESOLVED / INFO
        """
        alert_repo = AlertRepository(pg_session)
        host = await host_repo.create(address="10.50.0.1")

        # 1. OPEN / HIGH (oldest)
        a1 = await alert_repo.create(
            host_id=host.id,
            scan_id=None,
            monitoring_event_id=None,
            alert=_make_alert(
                target_str="10.50.0.1",
                port=80,
                severity=Severity.HIGH,
                timestamp=_BASE_TIME,
            ),
        )

        # 2. OPEN / LOW
        a2 = await alert_repo.create(
            host_id=host.id,
            scan_id=None,
            monitoring_event_id=None,
            alert=_make_alert(
                target_str="10.50.0.1",
                port=81,
                severity=Severity.LOW,
                timestamp=_BASE_TIME + timedelta(minutes=1),
            ),
        )

        # 3. ACKNOWLEDGED / HIGH
        a3 = await alert_repo.create(
            host_id=host.id,
            scan_id=None,
            monitoring_event_id=None,
            alert=_make_alert(
                target_str="10.50.0.1",
                port=82,
                severity=Severity.HIGH,
                timestamp=_BASE_TIME + timedelta(minutes=2),
            ),
        )
        a3_life = acknowledge_alert(
            a3.to_lifecycle(), at=_BASE_TIME + timedelta(minutes=3)
        )
        await alert_repo.update_lifecycle(a3.id, a3_life)

        # 4. RESOLVED / HIGH
        a4 = await alert_repo.create(
            host_id=host.id,
            scan_id=None,
            monitoring_event_id=None,
            alert=_make_alert(
                target_str="10.50.0.1",
                port=83,
                severity=Severity.HIGH,
                timestamp=_BASE_TIME + timedelta(minutes=4),
            ),
        )
        a4_life = resolve_alert(a4.to_lifecycle(), at=_BASE_TIME + timedelta(minutes=5))
        await alert_repo.update_lifecycle(a4.id, a4_life)

        # 5. RESOLVED / INFO (newest)
        a5 = await alert_repo.create(
            host_id=host.id,
            scan_id=None,
            monitoring_event_id=None,
            alert=_make_alert(
                target_str="10.50.0.1",
                port=84,
                severity=Severity.INFO,
                timestamp=_BASE_TIME + timedelta(minutes=6),
            ),
        )
        a5_life = resolve_alert(a5.to_lifecycle(), at=_BASE_TIME + timedelta(minutes=7))
        await alert_repo.update_lifecycle(a5.id, a5_life)

        await pg_session.commit()

        # Query status=OPEN -> expected a2, a1 (newest first)
        open_items = await query_service.list_alerts(status=AlertStatus.OPEN)
        assert [i.id for i in open_items] == [a2.id, a1.id]

        # Query severity=HIGH -> expected a4, a3, a1 (newest first)
        high_items = await query_service.list_alerts(severity=Severity.HIGH)
        assert [i.id for i in high_items] == [a4.id, a3.id, a1.id]

        # Query status=RESOLVED, severity=HIGH -> expected a4 only
        res_high_items = await query_service.list_alerts(
            status=AlertStatus.RESOLVED, severity=Severity.HIGH
        )
        assert [i.id for i in res_high_items] == [a4.id]

        # Query status=OPEN, severity=HIGH with limit=1 -> expected a1 only
        limited_items = await query_service.list_alerts(
            status=AlertStatus.OPEN, severity=Severity.HIGH, limit=1
        )
        assert [i.id for i in limited_items] == [a1.id]
