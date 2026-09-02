"""Unit tests for MonitoringPersistenceService.

Validates the orchestration of repositories and transaction management
(commit/rollback) using mocks, without a real database.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.detection.engine import MonitoringEvent, MonitoringEventType
from app.monitoring.availability import HostAvailabilityResult, HostStatus
from app.monitoring.port_scanner import PortScanResult
from app.monitoring.target import NetworkTarget
from app.monitoring.tcp_probe import PortStatus, TcpProbeResult
from app.services.monitoring_persistence import MonitoringPersistenceService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_TARGET = NetworkTarget.parse("10.0.0.1")


def _make_snapshot() -> HostAvailabilityResult:
    probe = TcpProbeResult(
        target=_TARGET,
        port=80,
        status=PortStatus.OPEN,
        duration_ms=1.5,
    )
    scan_result = PortScanResult(
        target=_TARGET,
        started_at=_NOW,
        finished_at=_NOW,
        duration_ms=2.0,
        ports=(probe,),
    )
    return HostAvailabilityResult(
        target=_TARGET,
        status=HostStatus.AVAILABLE,
        response_time_ms=1.5,
        scan_result=scan_result,
    )


def _make_event() -> MonitoringEvent:
    return MonitoringEvent(
        event_type=MonitoringEventType.PORT_OPENED,
        target=_TARGET,
        timestamp=_NOW,
        port=80,
        previous_state="closed",
        current_state="open",
    )


def _setup_service() -> tuple[MagicMock, MonitoringPersistenceService]:
    """Return a mock session and a service with mocked repositories."""
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    service = MonitoringPersistenceService(session)
    service._host_repo = MagicMock()
    service._host_repo.get_by_address = AsyncMock()
    service._host_repo.create = AsyncMock()

    service._scan_repo = MagicMock()
    service._scan_repo.create = AsyncMock()
    service._scan_repo.add_port_results = AsyncMock()

    service._event_repo = MagicMock()
    service._event_repo.create_many = AsyncMock()

    return session, service


# ---------------------------------------------------------------------------
# persist_cycle
# ---------------------------------------------------------------------------


class TestPersistCycle:
    @pytest.mark.asyncio
    async def test_finds_host_if_exists(self) -> None:
        """If host exists, it is reused and NOT created."""
        session, service = _setup_service()

        mock_host = MagicMock()
        mock_host.id = 1
        service._host_repo.get_by_address.return_value = mock_host

        mock_scan = MagicMock()
        mock_scan.id = 2
        service._scan_repo.create.return_value = mock_scan
        service._event_repo.create_many.return_value = []

        await service.persist_cycle(_make_snapshot(), [])

        service._host_repo.get_by_address.assert_awaited_once_with("10.0.0.1")
        service._host_repo.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_host_if_not_exists(self) -> None:
        """If host does not exist, it is created."""
        session, service = _setup_service()

        service._host_repo.get_by_address.return_value = None
        mock_host = MagicMock()
        mock_host.id = 1
        service._host_repo.create.return_value = mock_host

        mock_scan = MagicMock()
        mock_scan.id = 2
        service._scan_repo.create.return_value = mock_scan

        await service.persist_cycle(_make_snapshot(), [])

        service._host_repo.create.assert_awaited_once_with(address="10.0.0.1")

    @pytest.mark.asyncio
    async def test_commits_on_success(self) -> None:
        """A successful cycle must commit the transaction."""
        session, service = _setup_service()
        service._host_repo.get_by_address.return_value = MagicMock()
        service._scan_repo.create.return_value = MagicMock()

        await service.persist_cycle(_make_snapshot(), [])

        session.commit.assert_awaited_once()
        session.rollback.assert_not_called()

    @pytest.mark.asyncio
    async def test_rolls_back_and_raises_on_error(self) -> None:
        """If any repo fails, the transaction is rolled back and error re-raised."""
        session, service = _setup_service()

        mock_host = MagicMock()
        service._host_repo.get_by_address.return_value = mock_host

        # Simulate failure during scan creation
        error = RuntimeError("DB down")
        service._scan_repo.create.side_effect = error

        with pytest.raises(RuntimeError, match="DB down"):
            await service.persist_cycle(_make_snapshot(), [])

        session.commit.assert_not_called()
        session.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_passes_port_results_correctly(self) -> None:
        """Port results from the snapshot are mapped and passed to scan_repo."""
        session, service = _setup_service()
        service._host_repo.get_by_address.return_value = MagicMock(id=10)
        service._scan_repo.create.return_value = MagicMock(id=20)

        snapshot = _make_snapshot()
        await service.persist_cycle(snapshot, [])

        service._scan_repo.add_port_results.assert_awaited_once()
        args, kwargs = service._scan_repo.add_port_results.call_args
        assert kwargs["scan_id"] == 20
        results = kwargs["results"]
        assert len(results) == 1
        assert results[0].port == 80
        assert results[0].status == "open"
        assert results[0].response_time_ms == 1.5

    @pytest.mark.asyncio
    async def test_passes_events_correctly(self) -> None:
        """Events are passed to event_repo with the correct host_id and scan_id."""
        session, service = _setup_service()
        service._host_repo.get_by_address.return_value = MagicMock(id=10)
        service._scan_repo.create.return_value = MagicMock(id=20)

        event = _make_event()
        await service.persist_cycle(_make_snapshot(), [event])

        service._event_repo.create_many.assert_awaited_once_with(
            host_id=10,
            scan_id=20,
            events=[event],
        )
