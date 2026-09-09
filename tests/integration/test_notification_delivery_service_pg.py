"""Integration tests for NotificationDeliveryService with PostgreSQL persistence."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.detection.alerts import AlertType, SecurityAlert, Severity
from app.monitoring.target import NetworkTarget
from app.notifications.policy import NotificationPolicy
from app.notifications.webhook import WebhookNotificationSender
from app.repositories.alert import AlertRepository
from app.repositories.host import HostRepository
from app.repositories.notification_delivery import NotificationDeliveryRepository
from app.services.notification_delivery import NotificationDeliveryService

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 9, 9, 14, 0, 0, tzinfo=UTC)
_TARGET = NetworkTarget.parse("10.0.0.1")


class TestNotificationDeliveryServicePg:
    async def test_deliver_alerts_end_to_end_persists_in_postgresql(
        self,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        alert_repo = AlertRepository(pg_session)
        delivery_repo = NotificationDeliveryRepository(pg_session)

        # 1. Create host and alert in PostgreSQL
        host = await host_repo.create(address="192.168.1.100")
        alert_low = SecurityAlert(
            target=_TARGET,
            port=80,
            alert_type=AlertType.PORT_CLOSED,
            severity=Severity.LOW,
            message="Port 80 closed",
            timestamp=_NOW,
            source_event_type="port_closed",
        )
        alert_high = SecurityAlert(
            target=_TARGET,
            port=443,
            alert_type=AlertType.NEW_OPEN_PORT,
            severity=Severity.HIGH,
            message="Port 443 open",
            timestamp=_NOW,
            source_event_type="port_opened",
        )

        rec_low = await alert_repo.create(
            host_id=host.id, scan_id=None, monitoring_event_id=None, alert=alert_low
        )
        rec_high = await alert_repo.create(
            host_id=host.id, scan_id=None, monitoring_event_id=None, alert=alert_high
        )

        # 2. Mock HTTPX client to return HTTP 200 for webhook
        async def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"status": "ok"})

        mock_transport = httpx.MockTransport(mock_handler)
        async with httpx.AsyncClient(transport=mock_transport) as mock_client:
            webhook_sender = WebhookNotificationSender(
                url="https://webhook.example.com/alerts",
                client=mock_client,
            )

            service = NotificationDeliveryService(
                session=pg_session,
                policy=NotificationPolicy(minimum_severity=Severity.HIGH),
                sender=webhook_sender,
                delivery_repo=delivery_repo,
            )

            # 3. Deliver alerts
            results = await service.deliver_alerts(
                alerts=[alert_low, alert_high],
                alert_records=[rec_low, rec_high],
            )

        # 4. Verify only HIGH alert was delivered and persisted
        assert len(results) == 1
        assert results[0].success is True

        # Check records in PostgreSQL
        deliveries_high = await delivery_repo.list_by_alert(rec_high.id)
        assert len(deliveries_high) == 1
        assert deliveries_high[0].success is True
        assert deliveries_high[0].channel == "webhook"

        deliveries_low = await delivery_repo.list_by_alert(rec_low.id)
        assert len(deliveries_low) == 0
