"""Unit tests for AlertTriageService using mocks (no real database)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.detection.alerts import (
    AlertLifecycle,
    AlertStatus,
    InvalidAlertStateTransitionError,
)
from app.models.security_alert import SecurityAlertRecord
from app.repositories.alert import AlertRepository
from app.services.alert_triage import (
    AlertNotFoundError,
    AlertTriageService,
)

_BASE_TIME = datetime(2026, 9, 8, 12, 0, 0, tzinfo=UTC)


def _make_mock_record(
    *,
    alert_id: int = 1,
    status: str = "OPEN",
    acknowledged_at: datetime | None = None,
    resolved_at: datetime | None = None,
    created_at: datetime = _BASE_TIME,
) -> SecurityAlertRecord:
    record = MagicMock(spec=SecurityAlertRecord)
    record.id = alert_id
    record.host_id = 10
    record.scan_id = 20
    record.monitoring_event_id = 30
    record.alert_type = "new_open_port"
    record.severity = "high"
    record.message = "Port 80 newly open"
    record.port = 80
    record.status = status
    record.status_enum = AlertStatus(status)
    record.acknowledged_at = acknowledged_at
    record.resolved_at = resolved_at
    record.created_at = created_at
    record.to_lifecycle.return_value = AlertLifecycle(
        status=record.status_enum,
        acknowledged_at=acknowledged_at,
        resolved_at=resolved_at,
    )
    return record


@pytest.fixture
def mock_session() -> MagicMock:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def mock_alert_repo() -> MagicMock:
    repo = MagicMock(spec=AlertRepository)
    repo.get_by_id = AsyncMock()
    repo.update_lifecycle = AsyncMock()
    return repo


@pytest.fixture
def service(mock_session: MagicMock, mock_alert_repo: MagicMock) -> AlertTriageService:
    return AlertTriageService(mock_session, alert_repo=mock_alert_repo)


class TestAlertTriageServiceInit:
    def test_default_repo_instantiation(self, mock_session: MagicMock) -> None:
        service = AlertTriageService(mock_session)
        assert isinstance(service._alert_repo, AlertRepository)
        assert service._session is mock_session


class TestGetAlert:
    @pytest.mark.asyncio
    async def test_get_alert_found(
        self, service: AlertTriageService, mock_alert_repo: MagicMock
    ) -> None:
        record = _make_mock_record(alert_id=42)
        mock_alert_repo.get_by_id.return_value = record

        result = await service.get_alert(42)

        assert result is record
        mock_alert_repo.get_by_id.assert_awaited_once_with(42)

    @pytest.mark.asyncio
    async def test_get_alert_not_found(
        self, service: AlertTriageService, mock_alert_repo: MagicMock
    ) -> None:
        mock_alert_repo.get_by_id.return_value = None

        with pytest.raises(AlertNotFoundError) as exc_info:
            await service.get_alert(999)

        assert exc_info.value.alert_id == 999
        assert "Security alert with id=999 was not found" in str(exc_info.value)
        mock_alert_repo.get_by_id.assert_awaited_once_with(999)


class TestAcknowledge:
    @pytest.mark.asyncio
    async def test_acknowledge_success(
        self,
        service: AlertTriageService,
        mock_session: MagicMock,
        mock_alert_repo: MagicMock,
    ) -> None:
        record = _make_mock_record(alert_id=1, status="OPEN")
        mock_alert_repo.get_by_id.return_value = record

        ack_time = _BASE_TIME + timedelta(minutes=5)
        updated_record = _make_mock_record(
            alert_id=1,
            status="ACKNOWLEDGED",
            acknowledged_at=ack_time,
        )
        mock_alert_repo.update_lifecycle.return_value = updated_record

        result = await service.acknowledge(1, at=ack_time)

        assert result is updated_record
        mock_alert_repo.get_by_id.assert_awaited_once_with(1, for_update=True)
        mock_alert_repo.update_lifecycle.assert_awaited_once()
        call_args = mock_alert_repo.update_lifecycle.await_args
        assert call_args.args[0] == 1
        lifecycle_arg: AlertLifecycle = call_args.args[1]
        assert lifecycle_arg.status == AlertStatus.ACKNOWLEDGED
        assert lifecycle_arg.acknowledged_at == ack_time
        assert lifecycle_arg.resolved_at is None

        mock_session.commit.assert_awaited_once()
        mock_session.rollback.assert_not_called()

    @pytest.mark.asyncio
    async def test_acknowledge_default_timestamp_is_utc_now(
        self,
        service: AlertTriageService,
        mock_session: MagicMock,
        mock_alert_repo: MagicMock,
    ) -> None:
        record = _make_mock_record(alert_id=1, status="OPEN")
        mock_alert_repo.get_by_id.return_value = record
        updated_record = _make_mock_record(alert_id=1, status="ACKNOWLEDGED")
        mock_alert_repo.update_lifecycle.return_value = updated_record

        result = await service.acknowledge(1)

        assert result is updated_record
        mock_alert_repo.update_lifecycle.assert_awaited_once()
        lifecycle_arg: AlertLifecycle = (
            mock_alert_repo.update_lifecycle.await_args.args[1]
        )
        assert lifecycle_arg.status == AlertStatus.ACKNOWLEDGED
        assert lifecycle_arg.acknowledged_at is not None
        assert lifecycle_arg.acknowledged_at.tzinfo is not None
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_acknowledge_not_found(
        self,
        service: AlertTriageService,
        mock_session: MagicMock,
        mock_alert_repo: MagicMock,
    ) -> None:
        mock_alert_repo.get_by_id.return_value = None

        with pytest.raises(AlertNotFoundError) as exc_info:
            await service.acknowledge(404)

        assert exc_info.value.alert_id == 404
        mock_session.commit.assert_not_called()
        mock_session.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_acknowledge_invalid_transition_already_acknowledged(
        self,
        service: AlertTriageService,
        mock_session: MagicMock,
        mock_alert_repo: MagicMock,
    ) -> None:
        record = _make_mock_record(
            alert_id=1,
            status="ACKNOWLEDGED",
            acknowledged_at=_BASE_TIME,
        )
        mock_alert_repo.get_by_id.return_value = record

        with pytest.raises(InvalidAlertStateTransitionError):
            await service.acknowledge(1)

        mock_alert_repo.update_lifecycle.assert_not_called()
        mock_session.commit.assert_not_called()
        mock_session.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_acknowledge_invalid_transition_from_resolved(
        self,
        service: AlertTriageService,
        mock_session: MagicMock,
        mock_alert_repo: MagicMock,
    ) -> None:
        record = _make_mock_record(
            alert_id=1,
            status="RESOLVED",
            resolved_at=_BASE_TIME,
        )
        mock_alert_repo.get_by_id.return_value = record

        with pytest.raises(InvalidAlertStateTransitionError):
            await service.acknowledge(1)

        mock_alert_repo.update_lifecycle.assert_not_called()
        mock_session.commit.assert_not_called()
        mock_session.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_acknowledge_timestamp_before_creation(
        self,
        service: AlertTriageService,
        mock_session: MagicMock,
        mock_alert_repo: MagicMock,
    ) -> None:
        record = _make_mock_record(alert_id=1, status="OPEN", created_at=_BASE_TIME)
        mock_alert_repo.get_by_id.return_value = record

        earlier = _BASE_TIME - timedelta(minutes=10)
        with pytest.raises(ValueError, match="cannot be earlier than alert timestamp"):
            await service.acknowledge(1, at=earlier)

        mock_alert_repo.update_lifecycle.assert_not_called()
        mock_session.commit.assert_not_called()
        mock_session.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_acknowledge_update_lifecycle_missing_record(
        self,
        service: AlertTriageService,
        mock_session: MagicMock,
        mock_alert_repo: MagicMock,
    ) -> None:
        record = _make_mock_record(alert_id=1, status="OPEN")
        mock_alert_repo.get_by_id.return_value = record
        mock_alert_repo.update_lifecycle.return_value = None

        with pytest.raises(AlertNotFoundError):
            await service.acknowledge(1)

        mock_session.commit.assert_not_called()
        mock_session.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_acknowledge_database_commit_failure(
        self,
        service: AlertTriageService,
        mock_session: MagicMock,
        mock_alert_repo: MagicMock,
    ) -> None:
        record = _make_mock_record(alert_id=1, status="OPEN")
        mock_alert_repo.get_by_id.return_value = record
        mock_alert_repo.update_lifecycle.return_value = _make_mock_record(
            alert_id=1, status="ACKNOWLEDGED"
        )
        mock_session.commit.side_effect = RuntimeError("Database down")

        with pytest.raises(RuntimeError, match="Database down"):
            await service.acknowledge(1)

        mock_session.commit.assert_awaited_once()
        mock_session.rollback.assert_awaited_once()


class TestResolve:
    @pytest.mark.asyncio
    async def test_resolve_success_from_open(
        self,
        service: AlertTriageService,
        mock_session: MagicMock,
        mock_alert_repo: MagicMock,
    ) -> None:
        record = _make_mock_record(alert_id=2, status="OPEN")
        mock_alert_repo.get_by_id.return_value = record

        res_time = _BASE_TIME + timedelta(minutes=10)
        updated_record = _make_mock_record(
            alert_id=2,
            status="RESOLVED",
            resolved_at=res_time,
        )
        mock_alert_repo.update_lifecycle.return_value = updated_record

        result = await service.resolve(2, at=res_time)

        assert result is updated_record
        mock_alert_repo.get_by_id.assert_awaited_once_with(2, for_update=True)
        mock_alert_repo.update_lifecycle.assert_awaited_once()
        lifecycle_arg: AlertLifecycle = (
            mock_alert_repo.update_lifecycle.await_args.args[1]
        )
        assert lifecycle_arg.status == AlertStatus.RESOLVED
        assert lifecycle_arg.acknowledged_at is None
        assert lifecycle_arg.resolved_at == res_time

        mock_session.commit.assert_awaited_once()
        mock_session.rollback.assert_not_called()

    @pytest.mark.asyncio
    async def test_resolve_success_from_acknowledged(
        self,
        service: AlertTriageService,
        mock_session: MagicMock,
        mock_alert_repo: MagicMock,
    ) -> None:
        ack_time = _BASE_TIME + timedelta(minutes=5)
        record = _make_mock_record(
            alert_id=3,
            status="ACKNOWLEDGED",
            acknowledged_at=ack_time,
        )
        mock_alert_repo.get_by_id.return_value = record

        res_time = _BASE_TIME + timedelta(minutes=15)
        updated_record = _make_mock_record(
            alert_id=3,
            status="RESOLVED",
            acknowledged_at=ack_time,
            resolved_at=res_time,
        )
        mock_alert_repo.update_lifecycle.return_value = updated_record

        result = await service.resolve(3, at=res_time)

        assert result is updated_record
        lifecycle_arg: AlertLifecycle = (
            mock_alert_repo.update_lifecycle.await_args.args[1]
        )
        assert lifecycle_arg.status == AlertStatus.RESOLVED
        assert lifecycle_arg.acknowledged_at == ack_time
        assert lifecycle_arg.resolved_at == res_time

        mock_session.commit.assert_awaited_once()
        mock_session.rollback.assert_not_called()

    @pytest.mark.asyncio
    async def test_resolve_default_timestamp_is_utc_now(
        self,
        service: AlertTriageService,
        mock_session: MagicMock,
        mock_alert_repo: MagicMock,
    ) -> None:
        record = _make_mock_record(alert_id=2, status="OPEN")
        mock_alert_repo.get_by_id.return_value = record
        updated_record = _make_mock_record(alert_id=2, status="RESOLVED")
        mock_alert_repo.update_lifecycle.return_value = updated_record

        result = await service.resolve(2)

        assert result is updated_record
        lifecycle_arg: AlertLifecycle = (
            mock_alert_repo.update_lifecycle.await_args.args[1]
        )
        assert lifecycle_arg.status == AlertStatus.RESOLVED
        assert lifecycle_arg.resolved_at is not None
        assert lifecycle_arg.resolved_at.tzinfo is not None
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_resolve_not_found(
        self,
        service: AlertTriageService,
        mock_session: MagicMock,
        mock_alert_repo: MagicMock,
    ) -> None:
        mock_alert_repo.get_by_id.return_value = None

        with pytest.raises(AlertNotFoundError) as exc_info:
            await service.resolve(404)

        assert exc_info.value.alert_id == 404
        mock_session.commit.assert_not_called()
        mock_session.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_resolve_invalid_transition_already_resolved(
        self,
        service: AlertTriageService,
        mock_session: MagicMock,
        mock_alert_repo: MagicMock,
    ) -> None:
        record = _make_mock_record(
            alert_id=2,
            status="RESOLVED",
            resolved_at=_BASE_TIME,
        )
        mock_alert_repo.get_by_id.return_value = record

        with pytest.raises(InvalidAlertStateTransitionError):
            await service.resolve(2)

        mock_alert_repo.update_lifecycle.assert_not_called()
        mock_session.commit.assert_not_called()
        mock_session.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_resolve_timestamp_before_creation(
        self,
        service: AlertTriageService,
        mock_session: MagicMock,
        mock_alert_repo: MagicMock,
    ) -> None:
        record = _make_mock_record(alert_id=2, status="OPEN", created_at=_BASE_TIME)
        mock_alert_repo.get_by_id.return_value = record

        earlier = _BASE_TIME - timedelta(minutes=10)
        with pytest.raises(ValueError, match="cannot be earlier than alert timestamp"):
            await service.resolve(2, at=earlier)

        mock_alert_repo.update_lifecycle.assert_not_called()
        mock_session.commit.assert_not_called()
        mock_session.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_resolve_timestamp_before_acknowledged(
        self,
        service: AlertTriageService,
        mock_session: MagicMock,
        mock_alert_repo: MagicMock,
    ) -> None:
        ack_time = _BASE_TIME + timedelta(minutes=10)
        record = _make_mock_record(
            alert_id=3,
            status="ACKNOWLEDGED",
            acknowledged_at=ack_time,
            created_at=_BASE_TIME,
        )
        mock_alert_repo.get_by_id.return_value = record

        earlier_than_ack = _BASE_TIME + timedelta(minutes=5)
        with pytest.raises(ValueError, match="cannot be earlier than acknowledged_at"):
            await service.resolve(3, at=earlier_than_ack)

        mock_alert_repo.update_lifecycle.assert_not_called()
        mock_session.commit.assert_not_called()
        mock_session.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_resolve_database_commit_failure(
        self,
        service: AlertTriageService,
        mock_session: MagicMock,
        mock_alert_repo: MagicMock,
    ) -> None:
        record = _make_mock_record(alert_id=2, status="OPEN")
        mock_alert_repo.get_by_id.return_value = record
        mock_alert_repo.update_lifecycle.return_value = _make_mock_record(
            alert_id=2, status="RESOLVED"
        )
        mock_session.commit.side_effect = RuntimeError("Database down")

        with pytest.raises(RuntimeError, match="Database down"):
            await service.resolve(2)

        mock_session.commit.assert_awaited_once()
        mock_session.rollback.assert_awaited_once()
