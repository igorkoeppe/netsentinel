"""PostgreSQL integration tests for scheduled scans.

Covers the repository (claiming due schedules), the management service and the
runner end to end: a fake scan function stands in for the network, everything
else (baseline lookup, detection engine, alert rules, persistence) is real.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.detection.alerts import AlertType
from app.models.scan import Scan
from app.models.security_alert import SecurityAlertRecord
from app.monitoring.availability import HostAvailabilityResult, HostStatus
from app.monitoring.port_scanner import PortScanResult
from app.monitoring.target import NetworkTarget
from app.monitoring.tcp_probe import PortStatus, TcpProbeResult
from app.repositories.host import HostRepository
from app.repositories.scan_schedule import (
    ScanScheduleRepository,
    ScheduleAlreadyExistsError,
)
from app.services.scan_schedule import ScanScheduleService
from app.services.scheduled_scan import ScheduledScanRunner

pytestmark = pytest.mark.integration

_T0 = datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC)
_ADDRESS = "192.168.50.10"


def _session_factory(session: AsyncSession):  # type: ignore[no-untyped-def]
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield session

    return factory


class FakeScanner:
    """Returns pre-programmed port states, one snapshot per call."""

    def __init__(self, *runs: dict[int, PortStatus]) -> None:
        self._runs = list(runs)
        self._at = _T0
        self.calls: list[tuple[str, list[int]]] = []

    async def __call__(
        self, target: NetworkTarget, ports: list[int]
    ) -> HostAvailabilityResult:
        self.calls.append((target.value, ports))
        states = self._runs.pop(0)
        self._at += timedelta(minutes=5)
        probes = tuple(
            TcpProbeResult(target=target, port=p, status=states[p], duration_ms=1.0)
            for p in sorted(ports)
        )
        return HostAvailabilityResult(
            target=target,
            status=HostStatus.AVAILABLE,
            response_time_ms=1.0,
            scan_result=PortScanResult(
                target=target,
                started_at=self._at,
                finished_at=self._at + timedelta(milliseconds=30),
                duration_ms=30.0,
                ports=probes,
            ),
        )


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


async def test_one_schedule_per_host(pg_session: AsyncSession) -> None:
    host = await HostRepository(pg_session).get_or_create(address=_ADDRESS)
    repo = ScanScheduleRepository(pg_session)
    schedule = await repo.create(
        host_id=host.id, ports=[22], interval_seconds=60, next_run_at=_T0
    )
    assert schedule.host.address == _ADDRESS
    assert schedule.created_at is not None

    with pytest.raises(ScheduleAlreadyExistsError):
        await repo.create(
            host_id=host.id, ports=[80], interval_seconds=60, next_run_at=_T0
        )
    await pg_session.rollback()


async def test_claim_due_only_takes_enabled_due_schedules(
    pg_session: AsyncSession,
) -> None:
    hosts = HostRepository(pg_session)
    repo = ScanScheduleRepository(pg_session)
    due = await repo.create(
        host_id=(await hosts.get_or_create(address="10.1.0.1")).id,
        ports=[22],
        interval_seconds=120,
        next_run_at=_T0 - timedelta(seconds=1),
    )
    await repo.create(
        host_id=(await hosts.get_or_create(address="10.1.0.2")).id,
        ports=[22],
        interval_seconds=120,
        next_run_at=_T0 + timedelta(seconds=1),
    )
    await repo.create(
        host_id=(await hosts.get_or_create(address="10.1.0.3")).id,
        ports=[22],
        interval_seconds=120,
        next_run_at=_T0 - timedelta(hours=1),
        enabled=False,
    )

    claimed = await repo.claim_due(_T0, limit=10)
    assert [s.id for s in claimed] == [due.id]
    assert claimed[0].host.address == "10.1.0.1"
    assert claimed[0].next_run_at == _T0 + timedelta(seconds=120)

    # Claiming moved next_run_at forward: nothing is due a second time.
    assert await repo.claim_due(_T0, limit=10) == []


async def test_claim_due_respects_limit_and_overdue_order(
    pg_session: AsyncSession,
) -> None:
    hosts = HostRepository(pg_session)
    repo = ScanScheduleRepository(pg_session)
    for i, delay in enumerate([10, 30, 20]):
        await repo.create(
            host_id=(await hosts.get_or_create(address=f"10.2.0.{i}")).id,
            ports=[22],
            interval_seconds=60,
            next_run_at=_T0 - timedelta(seconds=delay),
        )
    claimed = await repo.claim_due(_T0, limit=2)
    assert [s.host.address for s in claimed] == ["10.2.0.1", "10.2.0.2"]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


async def test_service_create_update_and_list(pg_session: AsyncSession) -> None:
    service = ScanScheduleService(pg_session, min_interval=60)
    created = await service.create_schedule(
        target=_ADDRESS, ports=[443, 22, 22], interval_seconds=600, now=_T0
    )
    assert created.address == _ADDRESS
    assert created.ports == (22, 443)
    assert created.next_run_at == _T0

    disabled = await service.update_schedule(created.id, enabled=False, now=_T0)
    assert disabled.enabled is False
    assert disabled.updated_at is not None

    later = _T0 + timedelta(hours=2)
    enabled = await service.update_schedule(
        created.id, enabled=True, ports=[8080], now=later
    )
    assert enabled.enabled is True
    assert enabled.ports == (8080,)
    assert enabled.next_run_at == later

    assert [s.id for s in await service.list_schedules(enabled=True)] == [created.id]
    assert await service.list_schedules(enabled=False) == []
    assert (await service.get_schedule(created.id)).address == _ADDRESS


# ---------------------------------------------------------------------------
# Runner end to end
# ---------------------------------------------------------------------------


async def _alerts(session: AsyncSession) -> list[SecurityAlertRecord]:
    rows = await session.scalars(
        select(SecurityAlertRecord).order_by(SecurityAlertRecord.id)
    )
    return list(rows.all())


async def test_scheduled_runs_persist_history_and_alert_on_port_changes(
    pg_session: AsyncSession,
) -> None:
    service = ScanScheduleService(pg_session, min_interval=60)
    schedule = await service.create_schedule(
        target=_ADDRESS, ports=[22, 80, 8080], interval_seconds=300, now=_T0
    )
    scanner = FakeScanner(
        {22: PortStatus.OPEN, 80: PortStatus.OPEN, 8080: PortStatus.CLOSED},
        # 8080 appears, 80 (previously open) closes.
        {22: PortStatus.OPEN, 80: PortStatus.CLOSED, 8080: PortStatus.OPEN},
    )
    runner = ScheduledScanRunner(_session_factory(pg_session), scan=scanner)

    # First run: no baseline yet, so history but no alerts.
    first = await runner.run_due(_T0)
    assert len(first) == 1
    assert first[0].error is None and first[0].alerts == []
    assert scanner.calls == [(_ADDRESS, [22, 80, 8080])]

    # Not due again until the interval has passed.
    assert await runner.run_due(_T0 + timedelta(seconds=299)) == []

    second = await runner.run_due(_T0 + timedelta(seconds=300))
    assert len(second) == 1
    result = second[0]
    assert result.event_count == 2
    # The detection engine orders port events by port number.
    assert [(a.alert_type, a.port) for a in result.alerts] == [
        (AlertType.PORT_CLOSED, 80),
        (AlertType.NEW_OPEN_PORT, 8080),
    ]

    scan_count = await pg_session.scalar(select(func.count(Scan.id)))
    assert scan_count == 2

    stored = await _alerts(pg_session)
    assert [(a.alert_type, a.port, a.scan_id) for a in stored] == [
        ("port_closed", 80, result.scan_id),
        ("new_open_port", 8080, result.scan_id),
    ]

    after = await service.get_schedule(schedule.id)
    assert after.last_scan_id == result.scan_id
    assert after.last_error is None
    assert after.last_run_at is not None


async def test_baseline_comes_from_any_previous_persisted_scan(
    pg_session: AsyncSession,
) -> None:
    """A scan persisted before the schedule existed is used as the baseline."""
    seed = ScheduledScanRunner(
        _session_factory(pg_session),
        scan=FakeScanner({22: PortStatus.OPEN, 3389: PortStatus.CLOSED}),
    )
    host = await HostRepository(pg_session).get_or_create(address=_ADDRESS)
    schedule = await ScanScheduleRepository(pg_session).create(
        host_id=host.id, ports=[22, 3389], interval_seconds=60, next_run_at=_T0
    )
    await pg_session.commit()
    await seed.run_due(_T0)

    runner = ScheduledScanRunner(
        _session_factory(pg_session),
        scan=FakeScanner({22: PortStatus.OPEN, 3389: PortStatus.OPEN}),
    )
    [result] = await runner.run_due(_T0 + timedelta(seconds=60))
    assert result.schedule_id == schedule.id
    assert [(a.alert_type, a.port) for a in result.alerts] == [
        (AlertType.NEW_OPEN_PORT, 3389)
    ]


async def test_failed_scan_is_recorded_on_the_schedule(
    pg_session: AsyncSession,
) -> None:
    service = ScanScheduleService(pg_session, min_interval=60)
    schedule = await service.create_schedule(
        target=_ADDRESS, ports=[22], interval_seconds=60, now=_T0
    )

    async def broken_scan(
        _target: NetworkTarget, _ports: list[int]
    ) -> HostAvailabilityResult:
        raise OSError("network is unreachable")

    runner = ScheduledScanRunner(
        _session_factory(pg_session), scan=broken_scan, clock=lambda: _T0
    )
    [result] = await runner.run_due(_T0)
    assert result.error == "OSError: network is unreachable"

    after = await service.get_schedule(schedule.id)
    assert after.last_error == "OSError: network is unreachable"
    assert after.last_run_at == _T0
    assert after.last_scan_id is None
    # The failed run still consumed its slot: next run is one interval later.
    assert after.next_run_at == _T0 + timedelta(seconds=60)
