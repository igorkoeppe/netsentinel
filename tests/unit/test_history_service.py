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
    def mock_alert_repo(self):
        repo = AsyncMock()
        repo.list_by_scan.return_value = []
        repo.count_by_scans.return_value = {}
        return repo

    @pytest.fixture
    def service(
        self,
        mock_session,
        mock_host_repo,
        mock_scan_repo,
        mock_event_repo,
        mock_alert_repo,
    ):
        service = HistoryService(mock_session)
        service._host_repo = mock_host_repo
        service._scan_repo = mock_scan_repo
        service._event_repo = mock_event_repo
        service._alert_repo = mock_alert_repo
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
        self, service, mock_host_repo, mock_scan_repo, mock_alert_repo
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
        mock_alert_repo.count_by_scans.return_value = {10: 2}

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
        assert s.alert_count == 2

        mock_scan_repo.list_by_host.assert_called_once_with(1, limit=5)
        mock_alert_repo.count_by_scans.assert_called_once_with([10])

    async def test_get_host_history_alert_counts_multiple_scans(
        self, service, mock_host_repo, mock_scan_repo, mock_alert_repo
    ):
        """Test alert_count for three scans (0, 1, 3 alerts)."""
        mock_host = MagicMock(id=1, address="127.0.0.1", enabled=True, name=None)
        mock_host_repo.get_by_address.return_value = mock_host

        now = datetime.now(UTC)
        scan1 = MagicMock(
            id=1, started_at=now, status="available", response_time_ms=1.0
        )
        scan2 = MagicMock(
            id=2, started_at=now, status="available", response_time_ms=1.0
        )
        scan3 = MagicMock(
            id=3, started_at=now, status="available", response_time_ms=1.0
        )
        mock_scan_repo.list_by_host.return_value = [scan1, scan2, scan3]
        mock_alert_repo.count_by_scans.return_value = {1: 0, 2: 1, 3: 3}

        result = await service.get_host_history("127.0.0.1")

        assert result is not None
        assert len(result.scans) == 3
        assert result.scans[0].alert_count == 0
        assert result.scans[1].alert_count == 1
        assert result.scans[2].alert_count == 3
        mock_alert_repo.count_by_scans.assert_called_once_with([1, 2, 3])

    async def test_get_scan_details_not_found(self, service, mock_scan_repo):
        mock_scan_repo.get_by_id.return_value = None
        result = await service.get_scan_details(99)
        assert result is None
        mock_scan_repo.get_by_id.assert_called_once_with(99)

    async def test_get_scan_details_without_alerts(
        self, service, mock_scan_repo, mock_event_repo, mock_alert_repo
    ):
        """Scan without alerts returns alerts=[]."""
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
        mock_event_repo.list_by_scan.return_value = []
        mock_alert_repo.list_by_scan.return_value = []

        result = await service.get_scan_details(99)

        assert result is not None
        assert result.scan_id == 99
        assert result.alerts == []

    async def test_get_scan_details_with_alerts(
        self, service, mock_scan_repo, mock_event_repo, mock_alert_repo
    ):
        """Scan with multiple alerts returns mapped AlertSummary items."""
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
            id=101,
            port=443,
            previous_state="closed",
            current_state="open",
            created_at=scan_time,
        )
        mock_ev.event_type = "port_opened"
        mock_event_repo.list_by_scan.return_value = [mock_ev]

        mock_alert1 = MagicMock(
            id=1,
            alert_type="new_open_port",
            severity="high",
            message="New TCP port 443 detected on 127.0.0.1.",
            port=443,
            created_at=scan_time,
            monitoring_event_id=101,
        )
        mock_alert2 = MagicMock(
            id=2,
            alert_type="host_down",
            severity="medium",
            message="Host 127.0.0.1 became unavailable.",
            port=None,
            created_at=scan_time,
            monitoring_event_id=None,
        )
        mock_alert_repo.list_by_scan.return_value = [mock_alert1, mock_alert2]

        result = await service.get_scan_details(99)

        assert result is not None
        assert result.scan_id == 99
        assert len(result.alerts) == 2

        a1 = result.alerts[0]
        assert a1.id == 1
        assert a1.alert_type == "new_open_port"
        assert a1.severity == "high"
        assert a1.message == "New TCP port 443 detected on 127.0.0.1."
        assert a1.port == 443
        assert a1.created_at == scan_time
        assert a1.monitoring_event_id == 101

        a2 = result.alerts[1]
        assert a2.id == 2
        assert a2.alert_type == "host_down"
        assert a2.severity == "medium"
        assert a2.message == "Host 127.0.0.1 became unavailable."
        assert a2.port is None
        assert a2.monitoring_event_id is None
