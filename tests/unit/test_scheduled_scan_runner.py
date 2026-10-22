"""Unit tests for ScheduledScanRunner (no database, no network)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.detection.engine import MonitoringEventType, detect_changes
from app.monitoring.availability import HostAvailabilityResult, HostStatus
from app.monitoring.port_scanner import PortScanResult
from app.monitoring.target import NetworkTarget
from app.monitoring.tcp_probe import PortStatus, TcpProbeResult
from app.services.scheduled_scan import ScheduledScanRunner, snapshot_from_scan

_NOW = datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC)
_TARGET = NetworkTarget.parse("127.0.0.1")


def _snapshot(ports: dict[int, PortStatus], at: datetime) -> HostAvailabilityResult:
    probes = tuple(
        TcpProbeResult(target=_TARGET, port=p, status=s, duration_ms=1.0)
        for p, s in sorted(ports.items())
    )
    return HostAvailabilityResult(
        target=_TARGET,
        status=HostStatus.AVAILABLE,
        response_time_ms=1.0,
        scan_result=PortScanResult(
            target=_TARGET, started_at=at, finished_at=at, duration_ms=1.0, ports=probes
        ),
    )


def _scan_record(status: str, ports: dict[int, str]) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        status=status,
        response_time_ms=2.5,
        started_at=_NOW,
        finished_at=_NOW + timedelta(milliseconds=40),
        port_results=[
            SimpleNamespace(port=p, status=s, response_time_ms=1.0)
            for p, s in sorted(ports.items())
        ],
    )


def test_snapshot_from_scan_rebuilds_detection_input() -> None:
    record = _scan_record("available", {22: "open", 80: "closed"})
    snapshot = snapshot_from_scan(record, _TARGET)  # type: ignore[arg-type]

    assert snapshot is not None
    assert snapshot.status is HostStatus.AVAILABLE
    assert snapshot.scan_result.duration_ms == pytest.approx(40.0)
    assert [(p.port, p.status) for p in snapshot.scan_result.ports] == [
        (22, PortStatus.OPEN),
        (80, PortStatus.CLOSED),
    ]


def test_rebuilt_baseline_feeds_the_existing_detection_engine() -> None:
    baseline = snapshot_from_scan(
        _scan_record("available", {22: "open", 80: "closed", 443: "open"}),  # type: ignore[arg-type]
        _TARGET,
    )
    current = _snapshot(
        {22: PortStatus.OPEN, 80: PortStatus.OPEN, 443: PortStatus.CLOSED},
        _NOW + timedelta(minutes=5),
    )
    events = detect_changes(baseline, current)
    assert [(e.event_type, e.port) for e in events] == [
        (MonitoringEventType.PORT_OPENED, 80),
        (MonitoringEventType.PORT_CLOSED, 443),
    ]


def test_snapshot_from_scan_with_unknown_status_returns_none() -> None:
    record = _scan_record("degraded", {22: "open"})
    assert snapshot_from_scan(record, _TARGET) is None  # type: ignore[arg-type]

    record = _scan_record("available", {22: "filtered"})
    assert snapshot_from_scan(record, _TARGET) is None  # type: ignore[arg-type]


def _factory(session: AsyncMock):  # type: ignore[no-untyped-def]
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncMock]:
        yield session

    return factory


def test_rejects_non_positive_batch_size() -> None:
    with pytest.raises(ValueError):
        ScheduledScanRunner(_factory(AsyncMock()), batch_size=0)


async def test_scan_failure_is_recorded_not_raised() -> None:
    session = AsyncMock()
    scan = AsyncMock(side_effect=OSError("network is unreachable"))
    repo = MagicMock()
    repo.record_run = AsyncMock()

    runner = ScheduledScanRunner(_factory(session), scan=scan, clock=lambda: _NOW)
    with patch("app.services.scheduled_scan.ScanScheduleRepository", return_value=repo):
        result = await runner.run_one(5, "127.0.0.1", [22])

    assert result.error == "OSError: network is unreachable"
    assert result.scan_id is None
    repo.record_run.assert_awaited_once_with(
        5, ran_at=_NOW, scan_id=None, error="OSError: network is unreachable"
    )
    session.commit.assert_awaited_once()


async def test_invalid_stored_target_is_recorded_without_scanning() -> None:
    scan = AsyncMock()
    repo = MagicMock()
    repo.record_run = AsyncMock()

    runner = ScheduledScanRunner(_factory(AsyncMock()), scan=scan, clock=lambda: _NOW)
    with patch("app.services.scheduled_scan.ScanScheduleRepository", return_value=repo):
        result = await runner.run_one(5, "bad target!", [22])

    assert result.error is not None and result.error.startswith("Invalid target")
    scan.assert_not_awaited()


async def test_failure_to_record_a_failure_is_only_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    repo = MagicMock()
    repo.record_run = AsyncMock(side_effect=RuntimeError("db down"))
    runner = ScheduledScanRunner(
        _factory(AsyncMock()), scan=AsyncMock(side_effect=OSError("boom"))
    )
    with patch("app.services.scheduled_scan.ScanScheduleRepository", return_value=repo):
        result = await runner.run_one(5, "127.0.0.1", [22])

    assert result.error == "OSError: boom"
    assert "Could not record failure of schedule 5" in caplog.text


async def test_run_due_claims_then_runs_each_schedule_in_order() -> None:
    session = AsyncMock()
    claimed = [
        SimpleNamespace(id=1, host=SimpleNamespace(address="10.0.0.1"), ports=[22]),
        SimpleNamespace(id=2, host=SimpleNamespace(address="10.0.0.2"), ports=[80]),
    ]
    repo = MagicMock()
    repo.claim_due = AsyncMock(return_value=claimed)

    runner = ScheduledScanRunner(_factory(session), batch_size=5)
    run_one = AsyncMock(side_effect=lambda sid, *_: SimpleNamespace(schedule_id=sid))
    with (
        patch("app.services.scheduled_scan.ScanScheduleRepository", return_value=repo),
        patch.object(runner, "run_one", new=run_one),
    ):
        results = await runner.run_due(_NOW)

    repo.claim_due.assert_awaited_once_with(_NOW, limit=5)
    session.commit.assert_awaited_once()
    assert [c.args for c in run_one.await_args_list] == [
        (1, "10.0.0.1", [22]),
        (2, "10.0.0.2", [80]),
    ]
    assert [r.schedule_id for r in results] == [1, 2]


async def test_run_due_rolls_back_when_claim_fails() -> None:
    session = AsyncMock()
    repo = MagicMock()
    repo.claim_due = AsyncMock(side_effect=RuntimeError("lock timeout"))

    runner = ScheduledScanRunner(_factory(session))
    with (
        patch("app.services.scheduled_scan.ScanScheduleRepository", return_value=repo),
        pytest.raises(RuntimeError),
    ):
        await runner.run_due(_NOW)
    session.rollback.assert_awaited_once()
