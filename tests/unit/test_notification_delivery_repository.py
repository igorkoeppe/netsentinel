"""Unit tests for NotificationDeliveryRepository.

Uses AsyncMock / MagicMock to simulate the SQLAlchemy AsyncSession.
No live database is required.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.notification_delivery import NotificationDeliveryRecord
from app.notifications.models import DeliveryResult, NotificationChannel
from app.repositories.notification_delivery import NotificationDeliveryRepository

_NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)


def _make_session() -> MagicMock:
    session = MagicMock()
    session.add = MagicMock()
    session.add_all = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.get = AsyncMock()
    session.execute = AsyncMock()
    return session


class TestNotificationDeliveryRepositoryCreate:
    async def test_create_persists_record_and_refreshes(self) -> None:
        session = _make_session()
        repo = NotificationDeliveryRepository(session)

        record = await repo.create(
            alert_id=1,
            channel="webhook",
            notification_id="notif-123",
            success=True,
            delivered_at=_NOW,
            error_message=None,
        )

        session.add.assert_called_once()
        added = session.add.call_args[0][0]
        assert isinstance(added, NotificationDeliveryRecord)
        assert added.alert_id == 1
        assert added.channel == "webhook"
        assert added.notification_id == "notif-123"
        assert added.success is True
        assert added.delivered_at == _NOW
        assert added.error_message is None

        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once_with(record)

    async def test_create_from_result_success(self) -> None:
        session = _make_session()
        repo = NotificationDeliveryRepository(session)

        result = DeliveryResult(
            success=True,
            channel=NotificationChannel.WEBHOOK,
            notification_id="notif-456",
            delivered_at=_NOW,
            error_message=None,
        )

        record = await repo.create_from_result(alert_id=42, result=result)

        assert record.alert_id == 42
        assert record.channel == "webhook"
        assert record.notification_id == "notif-456"
        assert record.success is True
        assert record.delivered_at == _NOW
        assert record.error_message is None

    async def test_create_from_result_failure(self) -> None:
        session = _make_session()
        repo = NotificationDeliveryRepository(session)

        result = DeliveryResult(
            success=False,
            channel=NotificationChannel.WEBHOOK,
            notification_id="notif-fail",
            delivered_at=None,
            error_message="HTTP 500 Internal Server Error",
        )

        record = await repo.create_from_result(alert_id=42, result=result)

        assert record.alert_id == 42
        assert record.channel == "webhook"
        assert record.notification_id == "notif-fail"
        assert record.success is False
        assert record.delivered_at is None
        assert record.error_message == "HTTP 500 Internal Server Error"

    async def test_create_many_from_results_empty_returns_empty(self) -> None:
        session = _make_session()
        repo = NotificationDeliveryRepository(session)

        records = await repo.create_many_from_results([])
        assert records == []
        session.add_all.assert_not_called()
        session.flush.assert_not_awaited()

    async def test_create_many_from_results_adds_all(self) -> None:
        session = _make_session()
        repo = NotificationDeliveryRepository(session)

        res1 = DeliveryResult(
            success=True,
            channel=NotificationChannel.WEBHOOK,
            notification_id="n1",
            delivered_at=_NOW,
        )
        res2 = DeliveryResult(
            success=False,
            channel=NotificationChannel.WEBHOOK,
            notification_id="n2",
            error_message="timeout",
        )

        records = await repo.create_many_from_results([(10, res1), (11, res2)])
        assert len(records) == 2
        session.add_all.assert_called_once()
        session.flush.assert_awaited_once()
        assert records[0].alert_id == 10
        assert records[0].success is True
        assert records[1].alert_id == 11
        assert records[1].success is False


class TestNotificationDeliveryRepositoryRead:
    async def test_get_by_id_calls_session_get(self) -> None:
        session = _make_session()
        expected = NotificationDeliveryRecord(
            id=5,
            alert_id=1,
            channel="webhook",
            notification_id="n5",
            success=True,
            created_at=_NOW,
        )
        session.get.return_value = expected

        repo = NotificationDeliveryRepository(session)
        actual = await repo.get_by_id(5)

        session.get.assert_awaited_once_with(NotificationDeliveryRecord, 5)
        assert actual is expected

    async def test_list_by_alert_executes_query(self) -> None:
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_result

        repo = NotificationDeliveryRepository(session)
        deliveries = await repo.list_by_alert(123)

        assert deliveries == []
        session.execute.assert_awaited_once()

    async def test_list_recent_rejects_non_positive_limit(self) -> None:
        session = _make_session()
        repo = NotificationDeliveryRepository(session)

        with pytest.raises(ValueError, match="positive integer"):
            await repo.list_recent(limit=0)

        with pytest.raises(ValueError, match="positive integer"):
            await repo.list_recent(limit=-1)

    async def test_count_by_alerts_empty_returns_empty_dict(self) -> None:
        session = _make_session()
        repo = NotificationDeliveryRepository(session)

        counts = await repo.count_by_alerts([])
        assert counts == {}
        session.execute.assert_not_awaited()

    async def test_count_by_alerts_returns_counts(self) -> None:
        session = _make_session()
        mock_result = MagicMock()
        mock_result.all.return_value = [(10, 2), (20, 1)]
        session.execute.return_value = mock_result

        repo = NotificationDeliveryRepository(session)
        counts = await repo.count_by_alerts([10, 20, 30])

        assert counts == {10: 2, 20: 1, 30: 0}
