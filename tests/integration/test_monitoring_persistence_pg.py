"""Integration tests for MonitoringPersistenceService against PostgreSQL.

These tests require ``TEST_DATABASE_URL`` to be set and are tagged with the
``integration`` marker so that they are excluded from the default ``pytest``
run::

    # Only unit tests (no database required):
    pytest

    # PostgreSQL integration tests (set TEST_DATABASE_URL first):
    #   pytest -m integration

Because the service explicitly calls ``await session.commit()``, we cannot
rely on the ``pg_session`` fixture which tries to rollback at the end of the test.
Instead, we use a separate fixture or clear the database after.
However, if we use ``pg_session`` and the service commits, the test data is
permanently written. Therefore, we must clean up the tables explicitly in
these tests or rely on the engine teardown.

Wait, our existing `pg_session` fixture wraps the test in a savepoint (nested tx)
and the commit from the service might actually just commit the savepoint or fail.
Let's see how `pg_session` is implemented. It uses `session.begin_nested()`.
When a service calls `session.commit()`, it commits the *outermost* transaction
if we don't manage it properly, OR it just commits the nested one.
In SQLAlchemy 2.0, if `pg_session` yields a session with `begin_nested()`,
calling `session.commit()` actually commits the savepoint and pops it.
To avoid issues, it's safer to just test it inside the existing `pg_session`
and see if it works as a unit of work.

Actually, we can just use a real session, commit, and then delete the data
to ensure no leftovers. Or we can just use `pg_session` if it works correctly
with `session.commit()`. Let's try with `pg_session` and a manual rollback/cleanup
if needed.

Actually, calling `session.commit()` will commit the real transaction unless
we bind the session to a connection with a savepoint. If it commits the real
transaction, data persists across tests!
Let's use a real connection and clean up.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.detection.alerts import AlertType, SecurityAlert, Severity
from app.detection.engine import MonitoringEvent, MonitoringEventType
from app.monitoring.availability import HostAvailabilityResult, HostStatus
from app.monitoring.port_scanner import PortScanResult
from app.monitoring.target import NetworkTarget
from app.monitoring.tcp_probe import PortStatus, TcpProbeResult
from app.repositories.alert import AlertRepository
from app.repositories.host import HostRepository
from app.repositories.monitoring_event import MonitoringEventRepository
from app.repositories.scan import ScanRepository
from app.services.monitoring_persistence import (
    AlertEventCorrelationError,
    MonitoringPersistenceService,
)

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _make_snapshot(
    address: str,
    status: HostStatus = HostStatus.AVAILABLE,
    ports: tuple[TcpProbeResult, ...] = (),
    timestamp: datetime = _NOW,
) -> HostAvailabilityResult:
    target = NetworkTarget.parse(address)
    scan_result = PortScanResult(
        target=target,
        started_at=timestamp,
        finished_at=timestamp + timedelta(seconds=1),
        duration_ms=1000.0,
        ports=ports,
    )
    return HostAvailabilityResult(
        target=target,
        status=status,
        response_time_ms=1000.0,
        scan_result=scan_result,
    )


def _probe(port: int, status: PortStatus = PortStatus.OPEN) -> TcpProbeResult:
    return TcpProbeResult(
        target=NetworkTarget.parse("127.0.0.1"),
        port=port,
        status=status,
        duration_ms=50.0,
    )


def _make_event(
    address: str, event_type: MonitoringEventType, port: int | None = None
) -> MonitoringEvent:
    return MonitoringEvent(
        event_type=event_type,
        target=NetworkTarget.parse(address),
        timestamp=_NOW,
        port=port,
        previous_state="closed" if port else "unavailable",
        current_state="open" if port else "available",
    )


def _make_alert(
    address: str,
    alert_type: AlertType,
    severity: Severity,
    port: int | None = None,
    source_event_type: str | None = None,
) -> SecurityAlert:
    if source_event_type is None:
        if alert_type == AlertType.NEW_OPEN_PORT:
            source_event_type = "port_opened"
        elif alert_type == AlertType.PORT_CLOSED:
            source_event_type = "port_closed"
        elif alert_type == AlertType.HOST_DOWN:
            source_event_type = "host_became_unavailable"
        elif alert_type == AlertType.HOST_RECOVERED:
            source_event_type = "host_became_available"
        else:
            source_event_type = str(alert_type.value)
    return SecurityAlert(
        alert_type=alert_type,
        severity=severity,
        target=NetworkTarget.parse(address),
        timestamp=_NOW,
        message="Test alert",
        port=port,
        source_event_type=source_event_type,
    )


@pytest.fixture(autouse=True)
async def cleanup_db(pg_session: AsyncSession) -> None:
    """Explicitly clean up tables before and after each integration test.

    Because the service calls ``commit()``, data will persist beyond the test.
    This fixture ensures we start with a clean slate and clean up afterwards.
    """
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


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------


class TestPersistCycleNewHost:
    async def test_persists_full_cycle_for_new_host(
        self, pg_session: AsyncSession
    ) -> None:
        """A new host must be created, along with its scan, ports, and events."""
        service = MonitoringPersistenceService(pg_session)
        snapshot = _make_snapshot(
            "10.1.0.1",
            HostStatus.AVAILABLE,
            (_probe(22, PortStatus.CLOSED), _probe(443, PortStatus.OPEN)),
        )
        events = [_make_event("10.1.0.1", MonitoringEventType.PORT_OPENED, 443)]

        result = await service.persist_cycle(snapshot, events)

        # Verify returned objects
        assert result.host.id is not None
        assert result.scan.id is not None
        assert len(result.events) == 1

        # Verify DB state directly via repositories
        host_repo = HostRepository(pg_session)
        scan_repo = ScanRepository(pg_session)
        event_repo = MonitoringEventRepository(pg_session)

        # Host
        host = await host_repo.get_by_address("10.1.0.1")
        assert host is not None

        # Scan & Ports
        scans = await scan_repo.list_by_host(host.id)
        assert len(scans) == 1
        scan_with_ports = await scan_repo.get_by_id(scans[0].id)
        assert scan_with_ports is not None
        assert len(scan_with_ports.port_results) == 2

        # Events
        records = await event_repo.list_by_scan(scan_with_ports.id)
        assert len(records) == 1
        assert records[0].port == 443


class TestPersistCycleExistingHost:
    async def test_reuses_existing_host(self, pg_session: AsyncSession) -> None:
        """If the host already exists, it is reused, avoiding duplication."""
        # Setup: create the host first
        host_repo = HostRepository(pg_session)
        await host_repo.create(address="10.2.0.1")
        await pg_session.commit()

        service = MonitoringPersistenceService(pg_session)
        snapshot = _make_snapshot("10.2.0.1")

        result1 = await service.persist_cycle(snapshot, [])
        result2 = await service.persist_cycle(snapshot, [])

        # Both cycles should use the same host ID
        assert result1.host.id == result2.host.id

        hosts = await host_repo.list()
        assert len(hosts) == 1


class TestPersistCycleNoEvents:
    async def test_persists_scan_without_events(self, pg_session: AsyncSession) -> None:
        """If events=[], the scan and port results are still persisted."""
        service = MonitoringPersistenceService(pg_session)
        snapshot = _make_snapshot("10.3.0.1", ports=(_probe(80, PortStatus.OPEN),))

        result = await service.persist_cycle(snapshot, [])

        assert len(result.events) == 0
        assert len(result.alerts) == 0

        scan_repo = ScanRepository(pg_session)
        scan = await scan_repo.get_by_id(result.scan.id)
        assert scan is not None
        assert len(scan.port_results) == 1

        alert_repo = AlertRepository(pg_session)
        alerts = await alert_repo.list_by_scan(result.scan.id)
        assert len(alerts) == 0


class TestPersistCycleWithAlerts:
    async def test_persists_one_event_and_one_alert(
        self, pg_session: AsyncSession
    ) -> None:
        """Alert is correctly correlated to the event and persisted."""
        service = MonitoringPersistenceService(pg_session)
        snapshot = _make_snapshot("10.8.0.1", ports=(_probe(443),))
        event = _make_event("10.8.0.1", MonitoringEventType.PORT_OPENED, 443)
        alert = _make_alert("10.8.0.1", AlertType.NEW_OPEN_PORT, Severity.HIGH, 443)
        alert = alert.__class__(
            **{**alert.__dict__, "source_event_type": "port_opened"}
        )

        result = await service.persist_cycle(snapshot, [event], [alert])

        assert len(result.events) == 1
        assert len(result.alerts) == 1

        record_event = result.events[0]
        record_alert = result.alerts[0]

        assert record_alert.host_id == result.host.id
        assert record_alert.scan_id == result.scan.id
        assert record_alert.monitoring_event_id == record_event.id

    async def test_persists_multiple_alerts(self, pg_session: AsyncSession) -> None:
        """Multiple alerts are correlated individually and persisted."""
        service = MonitoringPersistenceService(pg_session)
        snapshot = _make_snapshot("10.8.0.2")

        event1 = _make_event("10.8.0.2", MonitoringEventType.PORT_CLOSED, 22)
        event2 = _make_event("10.8.0.2", MonitoringEventType.PORT_OPENED, 443)
        event3 = _make_event(
            "10.8.0.2", MonitoringEventType.HOST_BECAME_UNAVAILABLE, None
        )

        alert1 = _make_alert("10.8.0.2", AlertType.PORT_CLOSED, Severity.LOW, 22)
        alert1 = alert1.__class__(
            **{**alert1.__dict__, "source_event_type": "port_closed"}
        )

        alert2 = _make_alert("10.8.0.2", AlertType.NEW_OPEN_PORT, Severity.HIGH, 443)
        alert2 = alert2.__class__(
            **{**alert2.__dict__, "source_event_type": "port_opened"}
        )

        alert3 = _make_alert("10.8.0.2", AlertType.HOST_DOWN, Severity.MEDIUM, None)
        alert3 = alert3.__class__(
            **{**alert3.__dict__, "source_event_type": "host_became_unavailable"}
        )

        result = await service.persist_cycle(
            snapshot,
            [event1, event2, event3],
            [alert1, alert2, alert3],
        )

        assert len(result.events) == 3
        assert len(result.alerts) == 3

        # Verify correlations
        alert_repo = AlertRepository(pg_session)
        records = await alert_repo.list_by_scan(result.scan.id)
        assert len(records) == 3
        assert records[0].alert_type == "port_closed"
        assert records[0].monitoring_event_id == result.events[0].id
        assert records[1].alert_type == "new_open_port"
        assert records[1].monitoring_event_id == result.events[1].id
        assert records[2].alert_type == "host_down"
        assert records[2].monitoring_event_id == result.events[2].id

    async def test_event_without_alert(self, pg_session: AsyncSession) -> None:
        """An event without an alert should be persisted normally."""
        service = MonitoringPersistenceService(pg_session)
        snapshot = _make_snapshot("10.8.0.3")
        event = _make_event("10.8.0.3", MonitoringEventType.HOST_BECAME_AVAILABLE, None)

        result = await service.persist_cycle(snapshot, [event], [])

        assert len(result.events) == 1
        assert len(result.alerts) == 0

    async def test_alert_without_matching_event_fails(
        self, pg_session: AsyncSession
    ) -> None:
        """An alert that cannot be correlated to any event raises
        AlertEventCorrelationError.
        """
        service = MonitoringPersistenceService(pg_session)
        snapshot = _make_snapshot("10.8.0.4")
        event = _make_event("10.8.0.4", MonitoringEventType.PORT_OPENED, 80)

        # Alert for port 443 but event is for port 80
        alert = _make_alert("10.8.0.4", AlertType.NEW_OPEN_PORT, Severity.HIGH, 443)
        alert = alert.__class__(
            **{**alert.__dict__, "source_event_type": "port_opened"}
        )

        with pytest.raises(AlertEventCorrelationError):
            await service.persist_cycle(snapshot, [event], [alert])


class TestPersistCycleMultipleCycles:
    async def test_persists_multiple_cycles_correctly(
        self, pg_session: AsyncSession
    ) -> None:
        """Multiple snapshots for the same host create independent scans and events."""
        service = MonitoringPersistenceService(pg_session)

        snap1 = _make_snapshot("10.4.0.1", ports=(_probe(22),), timestamp=_NOW)
        events1 = [_make_event("10.4.0.1", MonitoringEventType.PORT_OPENED, 22)]

        ts2 = _NOW + timedelta(minutes=5)
        snap2 = _make_snapshot(
            "10.4.0.1", ports=(_probe(22, PortStatus.CLOSED),), timestamp=ts2
        )
        events2 = [_make_event("10.4.0.1", MonitoringEventType.PORT_CLOSED, 22)]

        await service.persist_cycle(snap1, events1)
        await service.persist_cycle(snap2, events2)

        # Verify
        host_repo = HostRepository(pg_session)
        scan_repo = ScanRepository(pg_session)
        event_repo = MonitoringEventRepository(pg_session)

        host = await host_repo.get_by_address("10.4.0.1")
        assert host is not None

        scans = await scan_repo.list_by_host(host.id)
        assert len(scans) == 2

        all_events = await event_repo.list_by_host(host.id)
        assert len(all_events) == 2


class TestPersistCycleRollback:
    async def test_rolls_back_everything_on_error(
        self, pg_session: AsyncSession
    ) -> None:
        """If an error occurs during persistence, no partial data is left behind."""
        service = MonitoringPersistenceService(pg_session)
        snapshot = _make_snapshot("10.5.0.1", ports=(_probe(80),))
        events = [_make_event("10.5.0.1", MonitoringEventType.PORT_OPENED, 80)]

        # We mock event_repo.create_many to simulate a failure at the last step
        with patch.object(
            service._event_repo,
            "create_many",
            side_effect=IntegrityError("DB ERR", {}, None),
        ):
            with pytest.raises(IntegrityError):
                await service.persist_cycle(snapshot, events)

        # Host (step 1) and Scan (step 2) must not exist!
        host_repo = HostRepository(pg_session)
        host = await host_repo.get_by_address("10.5.0.1")
        assert host is None, "Host was not rolled back!"

    async def test_rolls_back_everything_on_alert_error(
        self, pg_session: AsyncSession
    ) -> None:
        """If an error occurs during alert persistence, no partial
        data is left behind.
        """
        service = MonitoringPersistenceService(pg_session)
        snapshot = _make_snapshot("10.5.0.2", ports=(_probe(80),))
        event = _make_event("10.5.0.2", MonitoringEventType.PORT_OPENED, 80)
        alert = _make_alert("10.5.0.2", AlertType.NEW_OPEN_PORT, Severity.HIGH, 80)
        alert = alert.__class__(
            **{**alert.__dict__, "source_event_type": "port_opened"}
        )

        with patch.object(
            service._alert_repo,
            "create_many",
            side_effect=IntegrityError("DB ERR", {}, None),
        ):
            with pytest.raises(IntegrityError):
                await service.persist_cycle(snapshot, [event], [alert])

        host_repo = HostRepository(pg_session)
        host = await host_repo.get_by_address("10.5.0.2")
        assert host is None

    async def test_existing_host_persists_after_rollback(
        self, pg_session: AsyncSession
    ) -> None:
        """Host created previously is unaffected by a rollback in a subsequent cycle."""
        host_repo = HostRepository(pg_session)
        await host_repo.create(address="10.5.0.3")
        await pg_session.commit()

        service = MonitoringPersistenceService(pg_session)
        snapshot = _make_snapshot("10.5.0.3", ports=(_probe(80),))
        event = _make_event("10.5.0.3", MonitoringEventType.PORT_OPENED, 80)
        alert = _make_alert("10.5.0.3", AlertType.NEW_OPEN_PORT, Severity.HIGH, 80)
        alert = alert.__class__(
            **{**alert.__dict__, "source_event_type": "port_opened"}
        )

        with patch.object(
            service._alert_repo,
            "create_many",
            side_effect=IntegrityError("DB ERR", {}, None),
        ):
            with pytest.raises(IntegrityError):
                await service.persist_cycle(snapshot, [event], [alert])

        host = await host_repo.get_by_address("10.5.0.3")
        assert host is not None

        scan_repo = ScanRepository(pg_session)
        scans = await scan_repo.list_by_host(host.id)
        assert len(scans) == 0

    async def test_session_reusable_after_rollback(
        self, pg_session: AsyncSession
    ) -> None:
        """The session is safely rolled back and can be used immediately after."""
        service = MonitoringPersistenceService(pg_session)
        snapshot = _make_snapshot("10.6.0.1")

        # Simulate failure
        with patch.object(
            service._scan_repo, "create", side_effect=RuntimeError("Fake error")
        ):
            with pytest.raises(RuntimeError):
                await service.persist_cycle(snapshot, [])

        # Session is clean, perform valid insert
        result = await service.persist_cycle(_make_snapshot("10.6.0.2"), [])
        assert result.host.id is not None


class TestThreeSnapshotsLifecycle:
    async def test_three_consecutive_snapshots_closed_open_closed(
        self, pg_session: AsyncSession
    ) -> None:
        """Scenario: CLOSED -> OPEN -> CLOSED across 3 consecutive cycles.

        Validates:
        - 3 scans persisted
        - 2 events persisted (PORT_OPENED in cycle 2, PORT_CLOSED in cycle 3)
        - 2 alerts persisted (NEW_OPEN_PORT in cycle 2, PORT_CLOSED in cycle 3)
        - All foreign keys (host_id, scan_id, monitoring_event_id) are
          correctly populated.
        """
        service = MonitoringPersistenceService(pg_session)
        target_addr = "10.9.0.1"

        # Cycle 1: port 80 is CLOSED (initial state, no previous state)
        ts1 = _NOW
        snap1 = _make_snapshot(
            target_addr, ports=(_probe(80, PortStatus.CLOSED),), timestamp=ts1
        )
        res1 = await service.persist_cycle(snap1, [], [])
        assert len(res1.events) == 0
        assert len(res1.alerts) == 0

        # Cycle 2: port 80 is OPEN -> PORT_OPENED event and NEW_OPEN_PORT alert
        ts2 = _NOW + timedelta(seconds=10)
        snap2 = _make_snapshot(
            target_addr, ports=(_probe(80, PortStatus.OPEN),), timestamp=ts2
        )
        event2 = _make_event(target_addr, MonitoringEventType.PORT_OPENED, 80)
        alert2 = _make_alert(target_addr, AlertType.NEW_OPEN_PORT, Severity.HIGH, 80)
        res2 = await service.persist_cycle(snap2, [event2], [alert2])
        assert len(res2.events) == 1
        assert len(res2.alerts) == 1

        # Cycle 3: port 80 is CLOSED -> PORT_CLOSED event and PORT_CLOSED alert
        ts3 = _NOW + timedelta(seconds=20)
        snap3 = _make_snapshot(
            target_addr, ports=(_probe(80, PortStatus.CLOSED),), timestamp=ts3
        )
        event3 = _make_event(target_addr, MonitoringEventType.PORT_CLOSED, 80)
        alert3 = _make_alert(target_addr, AlertType.PORT_CLOSED, Severity.LOW, 80)
        res3 = await service.persist_cycle(snap3, [event3], [alert3])
        assert len(res3.events) == 1
        assert len(res3.alerts) == 1

        # Assertions across database
        host_repo = HostRepository(pg_session)
        scan_repo = ScanRepository(pg_session)
        event_repo = MonitoringEventRepository(pg_session)
        alert_repo = AlertRepository(pg_session)

        host = await host_repo.get_by_address(target_addr)
        assert host is not None
        assert host.id == res1.host.id == res2.host.id == res3.host.id

        scans = await scan_repo.list_by_host(host.id)
        assert len(scans) == 3
        scan_ids = [s.id for s in scans]
        assert set(scan_ids) == {res1.scan.id, res2.scan.id, res3.scan.id}

        all_events = await event_repo.list_by_host(host.id)
        assert len(all_events) == 2
        # list_by_host returns items ordered by created_at DESC (most recent first)
        assert all_events[0].event_type == "port_closed"
        assert all_events[0].scan_id == res3.scan.id
        assert all_events[1].event_type == "port_opened"
        assert all_events[1].scan_id == res2.scan.id

        all_alerts = await alert_repo.list_by_host(host.id)
        assert len(all_alerts) == 2

        # Alert 3 (most recent)
        assert all_alerts[0].alert_type == "port_closed"
        assert all_alerts[0].host_id == host.id
        assert all_alerts[0].scan_id == res3.scan.id
        assert all_alerts[0].monitoring_event_id == res3.events[0].id

        # Alert 2
        assert all_alerts[1].alert_type == "new_open_port"
        assert all_alerts[1].host_id == host.id
        assert all_alerts[1].scan_id == res2.scan.id
        assert all_alerts[1].monitoring_event_id == res2.events[0].id

    async def test_persist_alert_with_custom_severity_pg(
        self,
        pg_session: AsyncSession,
    ) -> None:
        """Alerts generated with custom policy severities are properly
        persisted to PG.
        """
        from app.detection.rules import AlertPolicy, generate_alerts

        service = MonitoringPersistenceService(pg_session)
        target_addr = "192.168.10.150"
        policy = AlertPolicy(new_open_port_severity=Severity.CRITICAL)

        snap = _make_snapshot(
            target_addr, ports=(_probe(8080, PortStatus.OPEN),), timestamp=_NOW
        )
        event = _make_event(target_addr, MonitoringEventType.PORT_OPENED, 8080)
        alerts = generate_alerts([event], policy=policy)

        assert len(alerts) == 1
        assert alerts[0].severity == Severity.CRITICAL

        result = await service.persist_cycle(snap, [event], alerts)
        assert len(result.alerts) == 1
        assert result.alerts[0].severity == "critical"

        alert_repo = AlertRepository(pg_session)
        persisted = await alert_repo.get_by_id(result.alerts[0].id)
        assert persisted is not None
        assert persisted.severity == "critical"
        assert persisted.alert_type == "new_open_port"
        assert persisted.port == 8080

    async def test_persist_expected_and_unexpected_alerts_pg(
        self,
        pg_session: AsyncSession,
    ) -> None:
        """Expected and unexpected open port alerts are properly persisted to PG."""
        from app.detection.rules import AlertPolicy, generate_alerts

        service = MonitoringPersistenceService(pg_session)
        target_addr = "192.168.10.160"
        policy = AlertPolicy(expected_tcp_ports=frozenset({80}))

        snap = _make_snapshot(
            target_addr,
            ports=(
                _probe(80, PortStatus.OPEN),
                _probe(8080, PortStatus.OPEN),
            ),
            timestamp=_NOW,
        )
        event_exp = _make_event(target_addr, MonitoringEventType.PORT_OPENED, 80)
        event_unexp = _make_event(target_addr, MonitoringEventType.PORT_OPENED, 8080)
        alerts = generate_alerts([event_exp, event_unexp], policy=policy)

        assert len(alerts) == 2
        assert alerts[0].alert_type == AlertType.EXPECTED_OPEN_PORT
        assert alerts[0].severity == Severity.INFO
        assert alerts[1].alert_type == AlertType.UNEXPECTED_OPEN_PORT
        assert alerts[1].severity == Severity.HIGH

        result = await service.persist_cycle(snap, [event_exp, event_unexp], alerts)
        assert len(result.alerts) == 2

        alert_repo = AlertRepository(pg_session)
        persisted_exp = await alert_repo.get_by_id(result.alerts[0].id)
        assert persisted_exp is not None
        assert persisted_exp.alert_type == "expected_open_port"
        assert persisted_exp.severity == "info"
        assert persisted_exp.port == 80
        assert persisted_exp.monitoring_event_id == result.events[0].id

        persisted_unexp = await alert_repo.get_by_id(result.alerts[1].id)
        assert persisted_unexp is not None
        assert persisted_unexp.alert_type == "unexpected_open_port"
        assert persisted_unexp.severity == "high"
        assert persisted_unexp.port == 8080
        assert persisted_unexp.monitoring_event_id == result.events[1].id
