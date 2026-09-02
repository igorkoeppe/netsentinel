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

from app.detection.engine import MonitoringEvent, MonitoringEventType
from app.monitoring.availability import HostAvailabilityResult, HostStatus
from app.monitoring.port_scanner import PortScanResult
from app.monitoring.target import NetworkTarget
from app.monitoring.tcp_probe import PortStatus, TcpProbeResult
from app.repositories.host import HostRepository
from app.repositories.monitoring_event import MonitoringEventRepository
from app.repositories.scan import ScanRepository
from app.services.monitoring_persistence import MonitoringPersistenceService

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


@pytest.fixture(autouse=True)
async def cleanup_db(pg_session: AsyncSession) -> None:
    """Explicitly clean up tables before and after each integration test.

    Because the service calls ``commit()``, data will persist beyond the test.
    This fixture ensures we start with a clean slate and clean up afterwards.
    """
    await pg_session.execute(text("TRUNCATE TABLE monitoring_events CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE port_results CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE scans CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE hosts CASCADE"))
    await pg_session.commit()
    yield
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

        scan_repo = ScanRepository(pg_session)
        scan = await scan_repo.get_by_id(result.scan.id)
        assert scan is not None
        assert len(scan.port_results) == 1


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
