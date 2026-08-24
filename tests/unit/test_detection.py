"""Unit tests for the detection engine."""

from datetime import UTC, datetime

import pytest

from app.detection.engine import MonitoringEventType, detect_changes
from app.monitoring.availability import HostAvailabilityResult, HostStatus
from app.monitoring.port_scanner import PortScanResult
from app.monitoring.target import NetworkTarget
from app.monitoring.tcp_probe import PortStatus, TcpProbeResult


@pytest.fixture
def target():
    return NetworkTarget.parse("127.0.0.1")


def create_snapshot(
    target: NetworkTarget,
    host_status: HostStatus,
    ports: list[tuple[int, PortStatus]],
    timestamp: datetime | None = None,
) -> HostAvailabilityResult:
    """Helper to create concise snapshots for testing."""
    if timestamp is None:
        timestamp = datetime.now(UTC)

    probes = tuple(
        TcpProbeResult(target=target, port=p, status=s, duration_ms=1.0)
        for p, s in ports
    )

    return HostAvailabilityResult(
        target=target,
        status=host_status,
        response_time_ms=1.0,
        scan_result=PortScanResult(
            target=target,
            started_at=timestamp,
            finished_at=timestamp,
            duration_ms=1.0,
            ports=probes,
        ),
    )


def test_initial_snapshot(target):
    """Test 11 - Initial snapshot (previous=None) should return empty list."""
    current = create_snapshot(target, HostStatus.AVAILABLE, [(80, PortStatus.OPEN)])
    assert detect_changes(None, current) == []


def test_no_changes(target):
    """Teste 1 — nenhuma mudança"""
    prev = create_snapshot(target, HostStatus.AVAILABLE, [(80, PortStatus.OPEN)])
    curr = create_snapshot(target, HostStatus.AVAILABLE, [(80, PortStatus.OPEN)])
    assert detect_changes(prev, curr) == []


def test_port_opened(target):
    """Teste 2 — porta abriu"""
    prev = create_snapshot(target, HostStatus.AVAILABLE, [(80, PortStatus.CLOSED)])
    curr = create_snapshot(target, HostStatus.AVAILABLE, [(80, PortStatus.OPEN)])
    events = detect_changes(prev, curr)

    assert len(events) == 1
    assert events[0].event_type == MonitoringEventType.PORT_OPENED
    assert events[0].port == 80


def test_port_closed(target):
    """Teste 3 — porta fechou"""
    prev = create_snapshot(target, HostStatus.AVAILABLE, [(443, PortStatus.OPEN)])
    curr = create_snapshot(target, HostStatus.AVAILABLE, [(443, PortStatus.CLOSED)])
    events = detect_changes(prev, curr)

    assert len(events) == 1
    assert events[0].event_type == MonitoringEventType.PORT_CLOSED
    assert events[0].port == 443


def test_host_became_unavailable(target):
    """Teste 4 — host ficou indisponível"""
    prev = create_snapshot(target, HostStatus.AVAILABLE, [])
    curr = create_snapshot(target, HostStatus.UNAVAILABLE, [])
    events = detect_changes(prev, curr)

    assert len(events) == 1
    assert events[0].event_type == MonitoringEventType.HOST_BECAME_UNAVAILABLE
    assert events[0].port is None


def test_host_became_available(target):
    """Teste 5 — host voltou"""
    prev = create_snapshot(target, HostStatus.UNAVAILABLE, [])
    curr = create_snapshot(target, HostStatus.AVAILABLE, [])
    events = detect_changes(prev, curr)

    assert len(events) == 1
    assert events[0].event_type == MonitoringEventType.HOST_BECAME_AVAILABLE
    assert events[0].port is None


def test_multiple_changes(target):
    """Teste 6 — múltiplas mudanças"""
    prev = create_snapshot(
        target,
        HostStatus.AVAILABLE,
        [(22, PortStatus.OPEN), (80, PortStatus.OPEN), (443, PortStatus.CLOSED)],
    )
    curr = create_snapshot(
        target,
        HostStatus.AVAILABLE,
        [(22, PortStatus.CLOSED), (80, PortStatus.OPEN), (443, PortStatus.OPEN)],
    )
    events = detect_changes(prev, curr)

    assert len(events) == 2
    assert events[0].event_type == MonitoringEventType.PORT_CLOSED
    assert events[0].port == 22
    assert events[1].event_type == MonitoringEventType.PORT_OPENED
    assert events[1].port == 443


def test_different_order(target):
    """Teste 7 — ordem diferente (deve produzir o mesmo resultado)"""
    prev = create_snapshot(
        target,
        HostStatus.AVAILABLE,
        [(443, PortStatus.CLOSED), (22, PortStatus.OPEN), (80, PortStatus.OPEN)],
    )
    curr = create_snapshot(
        target,
        HostStatus.AVAILABLE,
        [(80, PortStatus.OPEN), (443, PortStatus.OPEN), (22, PortStatus.CLOSED)],
    )
    events = detect_changes(prev, curr)

    assert len(events) == 2
    assert events[0].event_type == MonitoringEventType.PORT_CLOSED
    assert events[0].port == 22
    assert events[1].event_type == MonitoringEventType.PORT_OPENED
    assert events[1].port == 443


def test_new_port_in_config(target):
    """Teste 8 — porta nova na configuração"""
    prev = create_snapshot(
        target, HostStatus.AVAILABLE, [(22, PortStatus.OPEN), (80, PortStatus.OPEN)]
    )
    curr = create_snapshot(
        target,
        HostStatus.AVAILABLE,
        [(22, PortStatus.OPEN), (80, PortStatus.OPEN), (443, PortStatus.OPEN)],
    )
    events = detect_changes(prev, curr)

    assert len(events) == 0


def test_removed_port_in_config(target):
    """Teste 9 — porta removida"""
    prev = create_snapshot(
        target,
        HostStatus.AVAILABLE,
        [(22, PortStatus.OPEN), (80, PortStatus.OPEN), (443, PortStatus.OPEN)],
    )
    curr = create_snapshot(
        target, HostStatus.AVAILABLE, [(22, PortStatus.OPEN), (80, PortStatus.OPEN)]
    )
    events = detect_changes(prev, curr)

    assert len(events) == 0


def test_ambiguous_states(target):
    """Teste 10 — estados ambíguos"""
    prev = create_snapshot(target, HostStatus.AVAILABLE, [(80, PortStatus.TIMEOUT)])
    curr = create_snapshot(target, HostStatus.AVAILABLE, [(80, PortStatus.UNREACHABLE)])
    events = detect_changes(prev, curr)

    assert len(events) == 0


def test_event_timestamp(target):
    """Teste 11 — timestamp do evento deve ser o do snapshot atual"""
    prev_ts = datetime(2023, 1, 1, 10, 0, 0, tzinfo=UTC)
    curr_ts = datetime(2023, 1, 1, 10, 0, 5, tzinfo=UTC)

    prev = create_snapshot(
        target, HostStatus.AVAILABLE, [(80, PortStatus.CLOSED)], timestamp=prev_ts
    )
    curr = create_snapshot(
        target, HostStatus.AVAILABLE, [(80, PortStatus.OPEN)], timestamp=curr_ts
    )

    events = detect_changes(prev, curr)

    assert len(events) == 1
    assert events[0].timestamp == curr_ts
