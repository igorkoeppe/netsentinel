"""Unit tests for AlertQueryService using mocks (no database)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.detection.alerts import AlertStatus, Severity
from app.models.host import Host
from app.models.security_alert import SecurityAlertRecord
from app.repositories.alert import AlertRepository
from app.services.alert_query import AlertListItem, AlertQueryService

_NOW = datetime(2026, 9, 8, 12, 0, 0, tzinfo=UTC)


def _make_mock_record(
    *,
    alert_id: int = 1,
    severity: str = "high",
    alert_type: str = "unexpected_open_port",
    status: str = "OPEN",
    target_address: str = "127.0.0.1",
    port: int | None = 8080,
    created_at: datetime = _NOW,
    acknowledged_at: datetime | None = None,
    resolved_at: datetime | None = None,
    has_host: bool = True,
) -> SecurityAlertRecord:
    record = MagicMock(spec=SecurityAlertRecord)
    record.id = alert_id
    record.severity = severity
    record.alert_type = alert_type
    record.status = status
    record.port = port
    record.created_at = created_at
    record.acknowledged_at = acknowledged_at
    record.resolved_at = resolved_at

    if has_host:
        host = MagicMock(spec=Host)
        host.address = target_address
        record.host = host
    else:
        record.host = None

    return record


@pytest.fixture
def mock_session() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_alert_repo() -> MagicMock:
    repo = MagicMock(spec=AlertRepository)
    repo.list_recent = AsyncMock()
    repo.get_by_id = AsyncMock()
    return repo


@pytest.fixture
def service(mock_session: MagicMock, mock_alert_repo: MagicMock) -> AlertQueryService:
    return AlertQueryService(mock_session, alert_repo=mock_alert_repo)


class TestAlertQueryServiceInit:
    def test_default_repo_instantiation(self, mock_session: MagicMock) -> None:
        service = AlertQueryService(mock_session)
        assert isinstance(service._alert_repo, AlertRepository)
        assert service._session is mock_session


class TestListAlerts:
    @pytest.mark.asyncio
    async def test_list_alerts_empty(
        self, service: AlertQueryService, mock_alert_repo: MagicMock
    ) -> None:
        mock_alert_repo.list_recent.return_value = []

        result = await service.list_alerts(limit=20)

        assert result == []
        mock_alert_repo.list_recent.assert_awaited_once_with(
            limit=20, status=None, severity=None
        )

    @pytest.mark.asyncio
    async def test_list_alerts_success(
        self, service: AlertQueryService, mock_alert_repo: MagicMock
    ) -> None:
        rec1 = _make_mock_record(
            alert_id=42,
            severity="high",
            alert_type="unexpected_open_port",
            status="OPEN",
            target_address="192.168.1.100",
            port=8080,
        )
        rec2 = _make_mock_record(
            alert_id=41,
            severity="medium",
            alert_type="host_down",
            status="RESOLVED",
            target_address="10.0.0.1",
            port=None,
            resolved_at=_NOW,
        )
        mock_alert_repo.list_recent.return_value = [rec1, rec2]

        result = await service.list_alerts(limit=10)

        assert len(result) == 2
        mock_alert_repo.list_recent.assert_awaited_once_with(
            limit=10, status=None, severity=None
        )

        item1 = result[0]
        assert isinstance(item1, AlertListItem)
        assert item1.id == 42
        assert item1.severity == "high"
        assert item1.alert_type == "unexpected_open_port"
        assert item1.status == "OPEN"
        assert item1.target == "192.168.1.100"
        assert item1.port == 8080
        assert item1.created_at == _NOW
        assert item1.acknowledged_at is None
        assert item1.resolved_at is None

        item2 = result[1]
        assert item2.id == 41
        assert item2.severity == "medium"
        assert item2.alert_type == "host_down"
        assert item2.status == "RESOLVED"
        assert item2.target == "10.0.0.1"
        assert item2.port is None
        assert item2.resolved_at == _NOW

    @pytest.mark.asyncio
    async def test_list_alerts_with_status_filter(
        self, service: AlertQueryService, mock_alert_repo: MagicMock
    ) -> None:
        rec = _make_mock_record(alert_id=1, status="OPEN")
        mock_alert_repo.list_recent.return_value = [rec]

        result = await service.list_alerts(status=AlertStatus.OPEN)

        assert len(result) == 1
        assert result[0].status == "OPEN"
        mock_alert_repo.list_recent.assert_awaited_once_with(
            limit=20, status=AlertStatus.OPEN, severity=None
        )

    @pytest.mark.asyncio
    async def test_list_alerts_with_status_acknowledged(
        self, service: AlertQueryService, mock_alert_repo: MagicMock
    ) -> None:
        rec = _make_mock_record(alert_id=2, status="ACKNOWLEDGED")
        mock_alert_repo.list_recent.return_value = [rec]

        result = await service.list_alerts(status=AlertStatus.ACKNOWLEDGED)

        assert len(result) == 1
        assert result[0].status == "ACKNOWLEDGED"
        mock_alert_repo.list_recent.assert_awaited_once_with(
            limit=20, status=AlertStatus.ACKNOWLEDGED, severity=None
        )

    @pytest.mark.asyncio
    async def test_list_alerts_with_status_resolved(
        self, service: AlertQueryService, mock_alert_repo: MagicMock
    ) -> None:
        rec = _make_mock_record(alert_id=3, status="RESOLVED")
        mock_alert_repo.list_recent.return_value = [rec]

        result = await service.list_alerts(status=AlertStatus.RESOLVED)

        assert len(result) == 1
        assert result[0].status == "RESOLVED"
        mock_alert_repo.list_recent.assert_awaited_once_with(
            limit=20, status=AlertStatus.RESOLVED, severity=None
        )

    @pytest.mark.asyncio
    async def test_list_alerts_with_severity_filter(
        self, service: AlertQueryService, mock_alert_repo: MagicMock
    ) -> None:
        rec = _make_mock_record(alert_id=1, severity="high")
        mock_alert_repo.list_recent.return_value = [rec]

        result = await service.list_alerts(severity=Severity.HIGH)

        assert len(result) == 1
        assert result[0].severity == "high"
        mock_alert_repo.list_recent.assert_awaited_once_with(
            limit=20, status=None, severity=Severity.HIGH
        )

    @pytest.mark.asyncio
    async def test_list_alerts_combined_filters(
        self, service: AlertQueryService, mock_alert_repo: MagicMock
    ) -> None:
        rec = _make_mock_record(alert_id=1, status="OPEN", severity="high")
        mock_alert_repo.list_recent.return_value = [rec]

        result = await service.list_alerts(
            limit=5,
            status=AlertStatus.OPEN,
            severity=Severity.HIGH,
        )

        assert len(result) == 1
        assert result[0].status == "OPEN"
        assert result[0].severity == "high"
        mock_alert_repo.list_recent.assert_awaited_once_with(
            limit=5, status=AlertStatus.OPEN, severity=Severity.HIGH
        )

    @pytest.mark.asyncio
    async def test_list_alerts_invalid_status_type(
        self, service: AlertQueryService, mock_alert_repo: MagicMock
    ) -> None:
        with pytest.raises(TypeError, match="status must be an AlertStatus"):
            await service.list_alerts(status="OPEN")  # type: ignore[arg-type]
        mock_alert_repo.list_recent.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_alerts_invalid_severity_type(
        self, service: AlertQueryService, mock_alert_repo: MagicMock
    ) -> None:
        with pytest.raises(TypeError, match="severity must be a Severity"):
            await service.list_alerts(severity="high")  # type: ignore[arg-type]
        mock_alert_repo.list_recent.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_alerts_record_without_host(
        self, service: AlertQueryService, mock_alert_repo: MagicMock
    ) -> None:
        rec = _make_mock_record(alert_id=1, has_host=False)
        mock_alert_repo.list_recent.return_value = [rec]

        result = await service.list_alerts()

        assert len(result) == 1
        assert result[0].target == ""

    @pytest.mark.asyncio
    async def test_list_alerts_invalid_limit(
        self, service: AlertQueryService, mock_alert_repo: MagicMock
    ) -> None:
        with pytest.raises(ValueError, match="limit must be a positive integer"):
            await service.list_alerts(limit=0)

        with pytest.raises(ValueError, match="limit must be a positive integer"):
            await service.list_alerts(limit=-5)

        mock_alert_repo.list_recent.assert_not_called()


class TestGetAlert:
    @pytest.mark.asyncio
    async def test_get_alert_found(
        self, service: AlertQueryService, mock_alert_repo: MagicMock
    ) -> None:
        rec = _make_mock_record(alert_id=10, target_address="127.0.0.1")
        mock_alert_repo.get_by_id.return_value = rec

        result = await service.get_alert(10)

        assert result is not None
        assert result.id == 10
        assert result.target == "127.0.0.1"
        mock_alert_repo.get_by_id.assert_awaited_once_with(10)

    @pytest.mark.asyncio
    async def test_get_alert_not_found(
        self, service: AlertQueryService, mock_alert_repo: MagicMock
    ) -> None:
        mock_alert_repo.get_by_id.return_value = None

        result = await service.get_alert(999)

        assert result is None
        mock_alert_repo.get_by_id.assert_awaited_once_with(999)
