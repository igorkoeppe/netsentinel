"""Unit tests for NotificationDeliveryService."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.detection.alerts import AlertStatus, AlertType, SecurityAlert, Severity
from app.monitoring.target import NetworkTarget
from app.notifications.models import (
    DeliveryResult,
    Notification,
    NotificationChannel,
)
from app.notifications.policy import NotificationPolicy
from app.notifications.sender import InMemoryNotificationSender
from app.services.notification_delivery import NotificationDeliveryService

_NOW = datetime(2026, 9, 9, 15, 0, 0, tzinfo=UTC)


def _make_alert(
    severity: Severity = Severity.HIGH,
    alert_type: AlertType = AlertType.NEW_OPEN_PORT,
    port: int | None = 443,
) -> SecurityAlert:
    return SecurityAlert(
        alert_type=alert_type,
        severity=severity,
        target=NetworkTarget.parse("192.168.1.10"),
        timestamp=_NOW,
        message=f"Test alert for port {port}",
        port=port,
        source_event_type="port_opened",
        status=AlertStatus.OPEN,
    )


def _make_mock_record(record_id: int = 1) -> MagicMock:
    rec = MagicMock()
    rec.id = record_id
    return rec


class TestNotificationDeliveryServiceThresholds:
    async def test_alert_below_threshold_is_skipped(self) -> None:
        mock_sender = MagicMock()
        mock_sender.send = AsyncMock()

        svc = NotificationDeliveryService(
            policy=NotificationPolicy(minimum_severity=Severity.HIGH),
            sender=mock_sender,
        )

        low_alert = _make_alert(severity=Severity.LOW)
        result = await svc.deliver_alert(low_alert)

        assert result is None
        mock_sender.send.assert_not_called()

    async def test_alert_at_threshold_is_delivered(self) -> None:
        mock_sender = MagicMock()
        expected_result = DeliveryResult(
            success=True,
            channel=NotificationChannel.WEBHOOK,
            notification_id="test-id",
            delivered_at=_NOW,
        )
        mock_sender.send = AsyncMock(return_value=expected_result)

        svc = NotificationDeliveryService(
            policy=NotificationPolicy(minimum_severity=Severity.HIGH),
            sender=mock_sender,
        )

        high_alert = _make_alert(severity=Severity.HIGH)
        result = await svc.deliver_alert(high_alert)

        assert result is expected_result
        mock_sender.send.assert_awaited_once()
        notification: Notification = mock_sender.send.call_args[0][0]
        assert notification.severity == "high"
        assert notification.channel == NotificationChannel.WEBHOOK

    async def test_alert_above_threshold_is_delivered(self) -> None:
        mock_sender = MagicMock()
        expected_result = DeliveryResult(
            success=True,
            channel=NotificationChannel.WEBHOOK,
            notification_id="crit-id",
            delivered_at=_NOW,
        )
        mock_sender.send = AsyncMock(return_value=expected_result)

        svc = NotificationDeliveryService(
            policy=NotificationPolicy(minimum_severity=Severity.HIGH),
            sender=mock_sender,
        )

        crit_alert = _make_alert(severity=Severity.CRITICAL)
        result = await svc.deliver_alert(crit_alert)

        assert result is expected_result
        mock_sender.send.assert_awaited_once()


class TestNotificationDeliveryServicePersistence:
    async def test_delivery_persists_to_database_when_session_and_alert_id_present(
        self,
    ) -> None:
        session = MagicMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()

        mock_repo = MagicMock()
        mock_repo.create_from_result = AsyncMock()

        mock_sender = MagicMock()
        delivery_res = DeliveryResult(
            success=True,
            channel=NotificationChannel.WEBHOOK,
            notification_id="persisted-id",
            delivered_at=_NOW,
        )
        mock_sender.send = AsyncMock(return_value=delivery_res)

        svc = NotificationDeliveryService(
            session=session,
            policy=NotificationPolicy(minimum_severity=Severity.HIGH),
            sender=mock_sender,
            delivery_repo=mock_repo,
        )

        alert = _make_alert(severity=Severity.HIGH)
        result = await svc.deliver_alert(alert, alert_id=99)

        assert result is delivery_res
        mock_repo.create_from_result.assert_awaited_once_with(
            alert_id=99,
            result=delivery_res,
        )
        session.commit.assert_awaited_once()
        session.rollback.assert_not_called()

    async def test_delivery_without_session_does_not_persist(self) -> None:
        mock_sender = MagicMock()
        mock_sender.send = AsyncMock(
            return_value=DeliveryResult(
                success=True,
                channel=NotificationChannel.WEBHOOK,
                notification_id="no-db",
                delivered_at=_NOW,
            )
        )

        svc = NotificationDeliveryService(
            session=None,
            policy=NotificationPolicy(minimum_severity=Severity.HIGH),
            sender=mock_sender,
        )

        alert = _make_alert(severity=Severity.HIGH)
        result = await svc.deliver_alert(alert, alert_id=12)

        assert result is not None
        assert result.success is True

    async def test_database_error_rolls_back_and_raises(self) -> None:
        session = MagicMock()
        session.commit = AsyncMock(side_effect=RuntimeError("DB write failed"))
        session.rollback = AsyncMock()

        mock_repo = MagicMock()
        mock_repo.create_from_result = AsyncMock()

        mock_sender = MagicMock()
        mock_sender.send = AsyncMock(
            return_value=DeliveryResult(
                success=True,
                channel=NotificationChannel.WEBHOOK,
                notification_id="err-id",
                delivered_at=_NOW,
            )
        )

        svc = NotificationDeliveryService(
            session=session,
            policy=NotificationPolicy(minimum_severity=Severity.HIGH),
            sender=mock_sender,
            delivery_repo=mock_repo,
        )

        alert = _make_alert(severity=Severity.HIGH)
        with pytest.raises(RuntimeError, match="DB write failed"):
            await svc.deliver_alert(alert, alert_id=77)

        session.rollback.assert_awaited_once()


class TestNotificationDeliveryServiceErrorHandling:
    async def test_sender_exception_caught_and_converted_to_failed_result(self) -> None:
        mock_sender = MagicMock()
        mock_sender.send = AsyncMock(side_effect=ConnectionResetError("Socket reset"))

        svc = NotificationDeliveryService(
            policy=NotificationPolicy(minimum_severity=Severity.HIGH),
            sender=mock_sender,
        )

        alert = _make_alert(severity=Severity.HIGH)
        result = await svc.deliver_alert(alert)

        assert result is not None
        assert result.success is False
        assert result.channel == NotificationChannel.WEBHOOK
        assert "Socket reset" in (result.error_message or "")

    async def test_no_sender_returns_none(self) -> None:
        svc = NotificationDeliveryService(
            policy=NotificationPolicy(minimum_severity=Severity.HIGH),
            sender=None,
        )

        alert = _make_alert(severity=Severity.HIGH)
        result = await svc.deliver_alert(alert)
        assert result is None


class TestNotificationDeliveryServiceBatch:
    async def test_deliver_alerts_with_records_filters_and_delivers(self) -> None:
        in_memory_sender = InMemoryNotificationSender()

        session = MagicMock()
        session.commit = AsyncMock()
        mock_repo = MagicMock()
        mock_repo.create_from_result = AsyncMock()

        svc = NotificationDeliveryService(
            session=session,
            policy=NotificationPolicy(minimum_severity=Severity.HIGH),
            sender=in_memory_sender,
            delivery_repo=mock_repo,
        )

        alerts = [
            _make_alert(severity=Severity.INFO, port=80),
            _make_alert(severity=Severity.HIGH, port=443),
            _make_alert(severity=Severity.LOW, port=8080),
            _make_alert(severity=Severity.CRITICAL, port=22),
        ]
        records = [
            _make_mock_record(1),
            _make_mock_record(2),
            _make_mock_record(3),
            _make_mock_record(4),
        ]

        results = await svc.deliver_alerts(alerts, alert_records=records)

        assert len(results) == 2
        assert in_memory_sender.count == 2

        # Verify calls to repository for HIGH (id=2) and CRITICAL (id=4)
        assert mock_repo.create_from_result.await_count == 2
        call_ids = [
            call.kwargs["alert_id"]
            for call in mock_repo.create_from_result.call_args_list
        ]
        assert call_ids == [2, 4]

    async def test_deliver_alerts_without_records(self) -> None:
        in_memory_sender = InMemoryNotificationSender()

        svc = NotificationDeliveryService(
            policy=NotificationPolicy(minimum_severity=Severity.HIGH),
            sender=in_memory_sender,
        )

        alerts = [
            _make_alert(severity=Severity.MEDIUM),
            _make_alert(severity=Severity.HIGH),
        ]

        results = await svc.deliver_alerts(alerts)

        assert len(results) == 1
        assert in_memory_sender.count == 1
        assert results[0].success is True
