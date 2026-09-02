from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.history import (
    HistoryService,
)

UTC = UTC


class TestHistoryService:
    @pytest.fixture
    def mock_session(self):
        return MagicMock()

    @pytest.fixture
    def mock_host_repo(self):
        return AsyncMock()

    @pytest.fixture
    def mock_scan_repo(self):
        return AsyncMock()

    @pytest.fixture
    def mock_event_repo(self):
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_session, mock_host_repo, mock_scan_repo, mock_event_repo):
        service = HistoryService(mock_session)
        service._host_repo = mock_host_repo
        service._scan_repo = mock_scan_repo
        service._event_repo = mock_event_repo
        return service

    async def test_get_host_history_host_not_found(self, service, mock_host_repo):
        mock_host_repo.get_by_address.return_value = None
        result = await service.get_host_history("192.168.1.1")
        assert result is None
        mock_host_repo.get_by_address.assert_called_once_with("192.168.1.1")

    async def test_get_host_history_invalid_limit(self, service):
        with pytest.raises(ValueError, match="limit must be a positive integer"):
            await service.get_host_history("127.0.0.1", limit=0)
        with pytest.raises(ValueError, match="limit must be a positive integer"):
            await service.get_host_history("127.0.0.1", limit=-1)

    async def test_get_host_history_success_empty_scans(
        self, service, mock_host_repo, mock_scan_repo
    ):
        mock_host = MagicMock(id=1, address="127.0.0.1", enabled=True)
        mock_host.name = "local"
        mock_host_repo.get_by_address.return_value = mock_host
        mock_scan_repo.list_by_host.return_value = []

        result = await service.get_host_history("127.0.0.1")

        assert result is not None
        assert result.host_id == 1
        assert result.address == "127.0.0.1"
        assert result.name == "local"
        assert result.enabled is True
        assert result.scans == []
        mock_scan_repo.list_by_host.assert_called_once_with(1, limit=20)

    async def test_get_host_history_with_scans(
        self, service, mock_host_repo, mock_scan_repo
    ):
        mock_host = MagicMock(id=1, address="127.0.0.1", enabled=True)
        mock_host.name = None
        mock_host_repo.get_by_address.return_value = mock_host

        scan_time = datetime(2023, 1, 1, tzinfo=UTC)
        mock_scan = MagicMock(
            id=10,
            started_at=scan_time,
            status="available",
            response_time_ms=5.0,
        )
        mock_scan_repo.list_by_host.return_value = [mock_scan]

        result = await service.get_host_history("127.0.0.1", limit=5)

        assert result is not None
        assert len(result.scans) == 1
        s = result.scans[0]
        assert s.scan_id == 10
        assert s.timestamp == scan_time
        assert s.status == "available"
        assert s.response_time_ms == 5.0
        assert s.port_count is None
        assert s.event_count is None

        mock_scan_repo.list_by_host.assert_called_once_with(1, limit=5)

    async def test_get_scan_details_not_found(self, service, mock_scan_repo):
        mock_scan_repo.get_by_id.return_value = None
        result = await service.get_scan_details(99)
        assert result is None
        mock_scan_repo.get_by_id.assert_called_once_with(99)

    async def test_get_scan_details_success(
        self, service, mock_scan_repo, mock_event_repo
    ):
        scan_time = datetime(2023, 1, 1, tzinfo=UTC)
        mock_pr = MagicMock(port=80, status="open", response_time_ms=1.5)
        mock_scan = MagicMock(
            id=99,
            status="available",
            response_time_ms=5.0,
            started_at=scan_time,
            finished_at=scan_time,
            port_results=[mock_pr],
        )
        mock_scan_repo.get_by_id.return_value = mock_scan

        mock_ev = MagicMock(
            port=80,
            previous_state="closed",
            current_state="open",
            created_at=scan_time,
        )
        mock_ev.event_type = "port_opened"
        mock_event_repo.list_by_scan.return_value = [mock_ev]

        result = await service.get_scan_details(99)

        assert result is not None
        assert result.scan_id == 99
        assert result.status == "available"
        assert result.response_time_ms == 5.0
        assert result.started_at == scan_time
        assert result.finished_at == scan_time

        assert len(result.ports) == 1
        assert result.ports[0].port == 80
        assert result.ports[0].status == "open"

        assert len(result.events) == 1
        assert result.events[0].event_type == "port_opened"
        assert result.events[0].port == 80
