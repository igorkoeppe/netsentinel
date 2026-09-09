"""Unit tests for CLI notifications and alert delivery integration."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.cli import run_monitor
from app.core.config import settings
from app.detection.alerts import AlertStatus, AlertType, SecurityAlert, Severity
from app.detection.engine import MonitoringEvent, MonitoringEventType
from app.monitoring.availability import HostAvailabilityResult, HostStatus
from app.monitoring.port_scanner import PortScanResult
from app.monitoring.target import NetworkTarget
from app.monitoring.tcp_probe import PortStatus, TcpProbeResult
from app.notifications.models import DeliveryResult, NotificationChannel
from app.services.monitoring_persistence import PersistedMonitoringCycle

_NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)


def _make_snapshot(
    port: int = 80, status: PortStatus = PortStatus.OPEN
) -> HostAvailabilityResult:
    target = NetworkTarget.parse("127.0.0.1")
    return HostAvailabilityResult(
        target=target,
        status=HostStatus.AVAILABLE,
        response_time_ms=1.5,
        scan_result=PortScanResult(
            target=target,
            started_at=_NOW,
            finished_at=_NOW,
            duration_ms=10.0,
            ports=(TcpProbeResult(target, port, status, 2.0),),
        ),
    )


class TestCliNotificationsIntegration:
    @patch("app.cli.monitor_host")
    @patch("app.cli.detect_changes")
    @patch("app.cli.generate_alerts")
    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.monitoring_persistence.MonitoringPersistenceService")
    @patch("app.services.notification_delivery.NotificationDeliveryService")
    async def test_monitor_persist_with_webhook_delivers_and_persists(
        self,
        mock_delivery_svc_cls: MagicMock,
        mock_persistence_svc_cls: MagicMock,
        mock_get_db_session: MagicMock,
        mock_get_engine: MagicMock,
        mock_generate_alerts: MagicMock,
        mock_detect_changes: MagicMock,
        mock_monitor_host: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With --persist and webhook URL set, eligible alerts trigger delivery
        and persistence.
        """
        monkeypatch.setattr(settings, "DATABASE_URL", "postgresql+asyncpg://mock/db")
        monkeypatch.setattr(
            settings, "NOTIFICATION_WEBHOOK_URL", "https://example.com/webhook"
        )
        mock_get_engine.return_value = MagicMock(dispose=AsyncMock())

        snapshot1 = _make_snapshot(port=80, status=PortStatus.CLOSED)
        snapshot2 = _make_snapshot(port=80, status=PortStatus.OPEN)

        async def mock_generator():
            yield snapshot1
            yield snapshot2

        mock_monitor_host.return_value = mock_generator()

        event = MonitoringEvent(
            event_type=MonitoringEventType.PORT_OPENED,
            target=NetworkTarget.parse("127.0.0.1"),
            timestamp=_NOW,
            port=80,
            previous_state="closed",
            current_state="open",
        )
        mock_detect_changes.return_value = [event]

        alert = SecurityAlert(
            alert_type=AlertType.NEW_OPEN_PORT,
            severity=Severity.HIGH,
            target=NetworkTarget.parse("127.0.0.1"),
            timestamp=_NOW,
            message="New open TCP port 80 detected",
            port=80,
            source_event_type="port_opened",
            status=AlertStatus.OPEN,
        )
        mock_generate_alerts.return_value = [alert]

        mock_record = MagicMock(id=42)
        mock_cycle = PersistedMonitoringCycle(
            host=MagicMock(),
            scan=MagicMock(),
            events=[MagicMock()],
            alerts=[mock_record],
        )
        mock_persistence_svc = MagicMock()
        mock_persistence_svc.persist_cycle = AsyncMock(return_value=mock_cycle)
        mock_persistence_svc_cls.return_value = mock_persistence_svc

        mock_delivery_svc = MagicMock()
        mock_delivery_svc.deliver_alerts = AsyncMock(
            return_value=[
                DeliveryResult(
                    success=True,
                    channel=NotificationChannel.WEBHOOK,
                    notification_id="n1",
                    delivered_at=_NOW,
                )
            ]
        )
        mock_delivery_svc_cls.return_value = mock_delivery_svc

        exit_code = await run_monitor("127.0.0.1", [80], 1, 2, True)

        assert exit_code == 0
        assert mock_persistence_svc.persist_cycle.await_count == 2
        mock_delivery_svc.deliver_alerts.assert_awaited_once()

        # Check call arguments
        call_kwargs = mock_delivery_svc.deliver_alerts.call_args.kwargs
        assert call_kwargs["alerts"] == [alert]
        assert call_kwargs["alert_records"] == [mock_record]

    @patch("app.cli.monitor_host")
    @patch("app.cli.detect_changes")
    @patch("app.cli.generate_alerts")
    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.monitoring_persistence.MonitoringPersistenceService")
    @patch("app.services.notification_delivery.NotificationDeliveryService")
    async def test_monitor_persist_without_webhook_url_skips_delivery(
        self,
        mock_delivery_svc_cls: MagicMock,
        mock_persistence_svc_cls: MagicMock,
        mock_get_db_session: MagicMock,
        mock_get_engine: MagicMock,
        mock_generate_alerts: MagicMock,
        mock_detect_changes: MagicMock,
        mock_monitor_host: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With --persist and NO webhook URL, no notifications are dispatched."""
        monkeypatch.setattr(settings, "DATABASE_URL", "postgresql+asyncpg://mock/db")
        monkeypatch.setattr(settings, "NOTIFICATION_WEBHOOK_URL", "")
        mock_get_engine.return_value = MagicMock(dispose=AsyncMock())

        snapshot1 = _make_snapshot(port=80, status=PortStatus.CLOSED)
        snapshot2 = _make_snapshot(port=80, status=PortStatus.OPEN)

        async def mock_generator():
            yield snapshot1
            yield snapshot2

        mock_monitor_host.return_value = mock_generator()

        event = MonitoringEvent(
            event_type=MonitoringEventType.PORT_OPENED,
            target=NetworkTarget.parse("127.0.0.1"),
            timestamp=_NOW,
            port=80,
        )
        mock_detect_changes.return_value = [event]

        alert = SecurityAlert(
            alert_type=AlertType.NEW_OPEN_PORT,
            severity=Severity.HIGH,
            target=NetworkTarget.parse("127.0.0.1"),
            timestamp=_NOW,
            message="New open TCP port 80 detected",
            port=80,
            source_event_type="port_opened",
        )
        mock_generate_alerts.return_value = [alert]

        mock_cycle = PersistedMonitoringCycle(
            host=MagicMock(),
            scan=MagicMock(),
            events=[MagicMock()],
            alerts=[MagicMock()],
        )
        mock_persistence_svc = MagicMock()
        mock_persistence_svc.persist_cycle = AsyncMock(return_value=mock_cycle)
        mock_persistence_svc_cls.return_value = mock_persistence_svc

        exit_code = await run_monitor("127.0.0.1", [80], 1, 2, True)

        assert exit_code == 0
        assert mock_persistence_svc.persist_cycle.await_count == 2
        mock_delivery_svc_cls.assert_not_called()

    @patch("app.cli.monitor_host")
    @patch("app.cli.detect_changes")
    @patch("app.cli.generate_alerts")
    @patch("app.services.notification_delivery.NotificationDeliveryService")
    async def test_monitor_non_persist_with_webhook_delivers_without_db(
        self,
        mock_delivery_svc_cls: MagicMock,
        mock_generate_alerts: MagicMock,
        mock_detect_changes: MagicMock,
        mock_monitor_host: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Without --persist, webhook sends if URL is set, without DB
        imports/sessions.
        """
        monkeypatch.setattr(
            settings, "NOTIFICATION_WEBHOOK_URL", "https://example.com/webhook"
        )

        snapshot1 = _make_snapshot(port=80, status=PortStatus.CLOSED)
        snapshot2 = _make_snapshot(port=80, status=PortStatus.OPEN)

        async def mock_generator():
            yield snapshot1
            yield snapshot2

        mock_monitor_host.return_value = mock_generator()

        event = MonitoringEvent(
            event_type=MonitoringEventType.PORT_OPENED,
            target=NetworkTarget.parse("127.0.0.1"),
            timestamp=_NOW,
            port=80,
        )
        mock_detect_changes.return_value = [event]

        alert = SecurityAlert(
            alert_type=AlertType.NEW_OPEN_PORT,
            severity=Severity.HIGH,
            target=NetworkTarget.parse("127.0.0.1"),
            timestamp=_NOW,
            message="New open TCP port 80 detected",
            port=80,
            source_event_type="port_opened",
        )
        mock_generate_alerts.return_value = [alert]

        mock_delivery_svc = MagicMock()
        mock_delivery_svc.deliver_alerts = AsyncMock(return_value=[])
        mock_delivery_svc_cls.return_value = mock_delivery_svc

        with patch.dict(sys.modules, {"app.db.session": None}):
            exit_code = await run_monitor("127.0.0.1", [80], 1, 2, False)
            assert exit_code == 0

        mock_delivery_svc.deliver_alerts.assert_awaited_once_with(alerts=[alert])
        # Verify session=None was passed to delivery service
        delivery_svc_kwargs = mock_delivery_svc_cls.call_args.kwargs
        assert delivery_svc_kwargs.get("session") is None
