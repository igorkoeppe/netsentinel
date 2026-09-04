"""Integration tests for AlertRepository against a real PostgreSQL database.

These tests require ``TEST_DATABASE_URL`` to be set and are tagged with the
``integration`` marker so that they are excluded from the default ``pytest``
run.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.detection.alerts import AlertType, SecurityAlert, Severity
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
