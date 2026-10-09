"""Integration tests for AlertRepository against a real PostgreSQL database.

These tests require ``TEST_DATABASE_URL`` to be set and are tagged with the
``integration`` marker so that they are excluded from the default ``pytest``
run.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.detection.alerts import (
    AlertLifecycle,
    AlertStatus,
    AlertType,
    SecurityAlert,
    Severity,
    acknowledge_alert,
    resolve_alert,
)
from app.detection.engine import MonitoringEvent, MonitoringEventType
from app.monitoring.target import NetworkTarget
from app.repositories.alert import AlertRepository
from app.repositories.host import HostRepository
from app.repositories.monitoring_event import MonitoringEventRepository
from app.repositories.scan import ScanRepository

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_TARGET = NetworkTarget.parse("10.0.0.1")


def _port_opened_alert(port: int, *, timestamp: datetime = _NOW) -> SecurityAlert:
    return SecurityAlert(
        target=_TARGET,
        port=port,
        alert_type=AlertType.NEW_OPEN_PORT,
        severity=Severity.HIGH,
        message=f"TCP port {port} is newly open.",
        timestamp=timestamp,
        source_event_type="port_opened",
    )


def _host_down_alert(*, timestamp: datetime = _NOW) -> SecurityAlert:
    return SecurityAlert(
        target=_TARGET,
        port=None,
        alert_type=AlertType.HOST_DOWN,
        severity=Severity.MEDIUM,
        message="Host became unavailable.",
        timestamp=timestamp,
        source_event_type="host_down",
    )


async def _make_host(host_repo: HostRepository, address: str) -> int:
    host = await host_repo.create(address=address)
    return host.id


async def _make_scan(scan_repo: ScanRepository, host_id: int) -> int:
    scan = await scan_repo.create(
        host_id=host_id,
        status="available",
        response_time_ms=1.0,
        started_at=_NOW,
        finished_at=None,
    )
    return scan.id


async def _make_event(
    event_repo: MonitoringEventRepository, host_id: int, scan_id: int
) -> int:
    event = MonitoringEvent(
        event_type=MonitoringEventType.PORT_OPENED,
        target=_TARGET,
        timestamp=_NOW,
        port=80,
        previous_state="closed",
        current_state="open",
    )
    record = await event_repo.create(host_id=host_id, scan_id=scan_id, event=event)
    return record.id


class TestCreateAlert:
    async def test_create_fields(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        event_repo: MonitoringEventRepository,
        pg_session: AsyncSession,
    ) -> None:
        """Create must store all fields correctly."""
        alert_repo = AlertRepository(pg_session)
        host_id = await _make_host(host_repo, "10.1.0.1")
        scan_id = await _make_scan(scan_repo, host_id)
        event_id = await _make_event(event_repo, host_id, scan_id)

        alert = _port_opened_alert(443)

        record = await alert_repo.create(
            host_id=host_id,
            scan_id=scan_id,
            monitoring_event_id=event_id,
            alert=alert,
        )
        record_id = record.id
        pg_session.expire_all()
        fetched = await alert_repo.get_by_id(record_id)

        assert fetched is not None
        assert fetched.alert_type == "new_open_port"
        assert fetched.severity == "high"
        assert fetched.port == 443
        assert fetched.host_id == host_id
        assert fetched.scan_id == scan_id
        assert fetched.monitoring_event_id == event_id

    async def test_create_host_alert_port_is_none(
        self,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        """HOST_DOWN alert must store port=None."""
        alert_repo = AlertRepository(pg_session)
        host_id = await _make_host(host_repo, "10.1.0.2")
        alert = _host_down_alert()

        record = await alert_repo.create(
            host_id=host_id, scan_id=None, monitoring_event_id=None, alert=alert
        )
        record_id = record.id
        pg_session.expire_all()
        fetched = await alert_repo.get_by_id(record_id)

        assert fetched is not None
        assert fetched.alert_type == "host_down"
        assert fetched.severity == "medium"
        assert fetched.port is None

    async def test_created_at_uses_alert_timestamp(
        self,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        """created_at must equal the alert's timestamp."""
        alert_repo = AlertRepository(pg_session)
        host_id = await _make_host(host_repo, "10.1.0.3")
        custom_ts = datetime(2025, 6, 15, 10, 30, 0, tzinfo=UTC)
        alert = _port_opened_alert(80, timestamp=custom_ts)

        record = await alert_repo.create(
            host_id=host_id, scan_id=None, monitoring_event_id=None, alert=alert
        )
        record_id = record.id
        pg_session.expire_all()
        fetched = await alert_repo.get_by_id(record_id)

        assert fetched is not None
        ca = fetched.created_at
        fetched_utc = ca.replace(tzinfo=UTC) if ca.tzinfo is None else ca
        assert fetched_utc == custom_ts


class TestCreateManyAlerts:
    async def test_create_many_persists_all(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        event_repo: MonitoringEventRepository,
        pg_session: AsyncSession,
    ) -> None:
        """create_many must persist exactly as many records as alerts provided."""
        alert_repo = AlertRepository(pg_session)
        host_id = await _make_host(host_repo, "10.2.0.1")
        scan_id = await _make_scan(scan_repo, host_id)
        event_id = await _make_event(event_repo, host_id, scan_id)

        alerts = [
            (_port_opened_alert(80), event_id),
            (_host_down_alert(), None),
        ]
        records = await alert_repo.create_many(
            host_id=host_id, scan_id=scan_id, alerts=alerts
        )

        assert len(records) == 2
        types = [r.alert_type for r in records]
        assert "new_open_port" in types
        assert "host_down" in types

    async def test_create_many_empty(
        self,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        alert_repo = AlertRepository(pg_session)
        host_id = await _make_host(host_repo, "10.2.0.2")
        result = await alert_repo.create_many(host_id=host_id, scan_id=None, alerts=[])
        assert result == []


class TestListAlerts:
    async def test_list_by_host(
        self,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        alert_repo = AlertRepository(pg_session)
        host_a = await _make_host(host_repo, "10.3.0.1")
        host_b = await _make_host(host_repo, "10.3.0.2")

        await alert_repo.create(
            host_id=host_a,
            scan_id=None,
            monitoring_event_id=None,
            alert=_port_opened_alert(80),
        )
        await alert_repo.create(
            host_id=host_b,
            scan_id=None,
            monitoring_event_id=None,
            alert=_host_down_alert(),
        )
        pg_session.expire_all()

        records = await alert_repo.list_by_host(host_a)
        assert len(records) == 1
        assert records[0].host_id == host_a

    async def test_list_by_scan(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        pg_session: AsyncSession,
    ) -> None:
        alert_repo = AlertRepository(pg_session)
        host_id = await _make_host(host_repo, "10.4.0.1")
        scan_a = await _make_scan(scan_repo, host_id)
        scan_b = await _make_scan(scan_repo, host_id)

        await alert_repo.create(
            host_id=host_id,
            scan_id=scan_a,
            monitoring_event_id=None,
            alert=_port_opened_alert(80),
        )
        await alert_repo.create(
            host_id=host_id,
            scan_id=scan_b,
            monitoring_event_id=None,
            alert=_host_down_alert(),
        )
        pg_session.expire_all()

        records = await alert_repo.list_by_scan(scan_a)
        assert len(records) == 1
        assert records[0].scan_id == scan_a


class TestCountByScans:
    async def test_count_by_scans(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        pg_session: AsyncSession,
    ) -> None:
        alert_repo = AlertRepository(pg_session)
        host_id = await _make_host(host_repo, "10.4.0.2")
        scan_a = await _make_scan(scan_repo, host_id)
        scan_b = await _make_scan(scan_repo, host_id)
        scan_c = await _make_scan(scan_repo, host_id)

        await alert_repo.create(
            host_id=host_id,
            scan_id=scan_a,
            monitoring_event_id=None,
            alert=_port_opened_alert(80),
        )
        await alert_repo.create(
            host_id=host_id,
            scan_id=scan_a,
            monitoring_event_id=None,
            alert=_port_opened_alert(443),
        )
        await alert_repo.create(
            host_id=host_id,
            scan_id=scan_b,
            monitoring_event_id=None,
            alert=_host_down_alert(),
        )

        counts = await alert_repo.count_by_scans([scan_a, scan_b, scan_c])
        assert counts == {scan_a: 2, scan_b: 1, scan_c: 0}

    async def test_count_by_scans_empty_list(
        self,
        pg_session: AsyncSession,
    ) -> None:
        alert_repo = AlertRepository(pg_session)
        counts = await alert_repo.count_by_scans([])
        assert counts == {}


class TestFKViolation:
    async def test_invalid_host_id_raises(self, pg_session: AsyncSession) -> None:
        alert_repo = AlertRepository(pg_session)
        with pytest.raises(IntegrityError):
            await alert_repo.create(
                host_id=999_999,
                scan_id=None,
                monitoring_event_id=None,
                alert=_port_opened_alert(80),
            )


class TestLifecyclePersistence:
    async def test_create_alert_defaults_to_open_lifecycle(
        self,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        alert_repo = AlertRepository(pg_session)
        host_id = await _make_host(host_repo, "10.5.0.1")
        record = await alert_repo.create(
            host_id=host_id,
            scan_id=None,
            monitoring_event_id=None,
            alert=_port_opened_alert(80),
        )

        assert record.status == "OPEN"
        assert record.status_enum == AlertStatus.OPEN
        assert record.acknowledged_at is None
        assert record.resolved_at is None

        lifecycle = record.to_lifecycle()
        assert lifecycle.status == AlertStatus.OPEN
        assert lifecycle.acknowledged_at is None
        assert lifecycle.resolved_at is None
        assert lifecycle.is_open is True
        assert lifecycle.is_acknowledged is False
        assert lifecycle.is_resolved is False

    async def test_create_many_alerts_defaults_to_open_lifecycle(
        self,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        alert_repo = AlertRepository(pg_session)
        host_id = await _make_host(host_repo, "10.5.0.2")
        records = await alert_repo.create_many(
            host_id=host_id,
            scan_id=None,
            alerts=[
                (_port_opened_alert(80), None),
                (_port_opened_alert(443), None),
            ],
        )

        assert len(records) == 2
        for r in records:
            assert r.status == "OPEN"
            assert r.acknowledged_at is None
            assert r.resolved_at is None
            assert r.status_enum == AlertStatus.OPEN

    async def test_update_lifecycle_acknowledge(
        self,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        alert_repo = AlertRepository(pg_session)
        host_id = await _make_host(host_repo, "10.5.0.3")
        created = await alert_repo.create(
            host_id=host_id,
            scan_id=None,
            monitoring_event_id=None,
            alert=_port_opened_alert(80, timestamp=_NOW),
        )

        alert_id = created.id
        ack_time = _NOW + timedelta(minutes=5)
        # Transition in domain
        ack_lifecycle = acknowledge_alert(created.to_lifecycle(), at=ack_time)
        assert ack_lifecycle.status == AlertStatus.ACKNOWLEDGED
        assert ack_lifecycle.acknowledged_at == ack_time

        # Update via repository
        updated = await alert_repo.update_lifecycle(alert_id, ack_lifecycle)
        assert updated is not None
        assert updated.id == alert_id
        assert updated.status == "ACKNOWLEDGED"
        assert updated.status_enum == AlertStatus.ACKNOWLEDGED
        assert updated.acknowledged_at == ack_time
        assert updated.resolved_at is None

        # Fetch fresh from database to confirm persistence
        pg_session.expire_all()
        refetched = await alert_repo.get_by_id(alert_id)
        assert refetched is not None
        assert refetched.status == "ACKNOWLEDGED"
        assert refetched.acknowledged_at == ack_time
        assert refetched.resolved_at is None

    async def test_update_lifecycle_resolve_after_acknowledge(
        self,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        alert_repo = AlertRepository(pg_session)
        host_id = await _make_host(host_repo, "10.5.0.4")
        created = await alert_repo.create(
            host_id=host_id,
            scan_id=None,
            monitoring_event_id=None,
            alert=_port_opened_alert(80, timestamp=_NOW),
        )
        alert_id = created.id

        # Step 1: Acknowledge
        ack_time = _NOW + timedelta(minutes=5)
        ack_lifecycle = acknowledge_alert(created.to_lifecycle(), at=ack_time)
        await alert_repo.update_lifecycle(alert_id, ack_lifecycle)

        # Step 2: Resolve
        res_time = _NOW + timedelta(minutes=15)
        res_lifecycle = resolve_alert(ack_lifecycle, at=res_time)
        updated = await alert_repo.update_lifecycle(alert_id, res_lifecycle)

        assert updated is not None
        assert updated.status == "RESOLVED"
        assert updated.status_enum == AlertStatus.RESOLVED
        assert updated.acknowledged_at == ack_time
        assert updated.resolved_at == res_time

        pg_session.expire_all()
        refetched = await alert_repo.get_by_id(alert_id)
        assert refetched is not None
        assert refetched.status == "RESOLVED"
        assert refetched.acknowledged_at == ack_time
        assert refetched.resolved_at == res_time

    async def test_update_lifecycle_direct_resolve(
        self,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        alert_repo = AlertRepository(pg_session)
        host_id = await _make_host(host_repo, "10.5.0.5")
        created = await alert_repo.create(
            host_id=host_id,
            scan_id=None,
            monitoring_event_id=None,
            alert=_port_opened_alert(80, timestamp=_NOW),
        )
        alert_id = created.id

        # Direct resolve from OPEN
        res_time = _NOW + timedelta(minutes=10)
        res_lifecycle = resolve_alert(created.to_lifecycle(), at=res_time)
        updated = await alert_repo.update_lifecycle(alert_id, res_lifecycle)

        assert updated is not None
        assert updated.status == "RESOLVED"
        assert updated.acknowledged_at is None
        assert updated.resolved_at == res_time

        pg_session.expire_all()
        refetched = await alert_repo.get_by_id(alert_id)
        assert refetched is not None
        assert refetched.status == "RESOLVED"
        assert refetched.acknowledged_at is None
        assert refetched.resolved_at == res_time

    async def test_update_lifecycle_nonexistent_alert_returns_none(
        self,
        pg_session: AsyncSession,
    ) -> None:
        alert_repo = AlertRepository(pg_session)
        result = await alert_repo.update_lifecycle(999_999, AlertLifecycle())
        assert result is None

    async def test_update_lifecycle_rollback(
        self,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        alert_repo = AlertRepository(pg_session)
        host_id = await _make_host(host_repo, "10.5.0.6")
        created = await alert_repo.create(
            host_id=host_id,
            scan_id=None,
            monitoring_event_id=None,
            alert=_port_opened_alert(80, timestamp=_NOW),
        )
        alert_id = created.id

        # Perform lifecycle update inside a nested transaction that rolls back
        ack_time = _NOW + timedelta(minutes=5)
        ack_lifecycle = acknowledge_alert(created.to_lifecycle(), at=ack_time)

        try:
            async with pg_session.begin_nested():
                await alert_repo.update_lifecycle(alert_id, ack_lifecycle)
                raise RuntimeError("Forced rollback of savepoint")
        except RuntimeError:
            pass

        pg_session.expire_all()
        refetched = await alert_repo.get_by_id(alert_id)
        assert refetched is not None
        # Must retain original OPEN state
        assert refetched.status == "OPEN"
        assert refetched.acknowledged_at is None
        assert refetched.resolved_at is None

    async def test_read_methods_preserve_lifecycle(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        pg_session: AsyncSession,
    ) -> None:
        alert_repo = AlertRepository(pg_session)
        host_id = await _make_host(host_repo, "10.5.0.7")
        scan_id = await _make_scan(scan_repo, host_id)

        created = await alert_repo.create(
            host_id=host_id,
            scan_id=scan_id,
            monitoring_event_id=None,
            alert=_port_opened_alert(80, timestamp=_NOW),
        )
        alert_id = created.id

        ack_time = _NOW + timedelta(minutes=5)
        ack_lifecycle = acknowledge_alert(created.to_lifecycle(), at=ack_time)
        await alert_repo.update_lifecycle(alert_id, ack_lifecycle)

        pg_session.expire_all()

        # 1. get_by_id
        by_id = await alert_repo.get_by_id(alert_id)
        assert by_id is not None
        assert by_id.status == "ACKNOWLEDGED"
        assert by_id.acknowledged_at == ack_time

        # 2. list_by_host
        by_host = await alert_repo.list_by_host(host_id)
        assert len(by_host) == 1
        assert by_host[0].status == "ACKNOWLEDGED"
        assert by_host[0].acknowledged_at == ack_time

        # 3. list_by_scan
        by_scan = await alert_repo.list_by_scan(scan_id)
        assert len(by_scan) == 1
        assert by_scan[0].status == "ACKNOWLEDGED"
        assert by_scan[0].acknowledged_at == ack_time


class TestGetById:
    async def test_get_by_id_eager_loads_host_without_missing_greenlet(
        self,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        """Confirm get_by_id eagerly loads the associated Host so that accessing
        record.host and record.host.address does not raise MissingGreenlet even
        after expire_all() detaches/invalidates session attributes.
        """
        alert_repo = AlertRepository(pg_session)
        host_id = await _make_host(host_repo, "10.200.1.5")
        created = await alert_repo.create(
            host_id=host_id,
            scan_id=None,
            monitoring_event_id=None,
            alert=_port_opened_alert(443),
        )
        await pg_session.commit()

        # Evict all loaded entities from session identity map
        pg_session.expire_all()

        record = await alert_repo.get_by_id(created.id)
        assert record is not None
        assert record.id == created.id
        # Accessing host relationship must NOT trigger lazy-load / MissingGreenlet
        assert record.host is not None
        assert record.host.id == host_id
        assert record.host.address == "10.200.1.5"

    async def test_get_by_id_not_found_returns_none(
        self,
        pg_session: AsyncSession,
    ) -> None:
        alert_repo = AlertRepository(pg_session)
        record = await alert_repo.get_by_id(999_999)
        assert record is None
