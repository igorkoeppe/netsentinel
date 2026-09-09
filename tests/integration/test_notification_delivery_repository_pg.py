"""Integration tests for NotificationDeliveryRepository against real PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.detection.alerts import AlertType, SecurityAlert, Severity
from app.monitoring.target import NetworkTarget
from app.notifications.models import DeliveryResult, NotificationChannel
from app.repositories.alert import AlertRepository
from app.repositories.host import HostRepository
from app.repositories.notification_delivery import NotificationDeliveryRepository

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
_TARGET = NetworkTarget.parse("10.0.0.1")


async def _make_alert_record(
    host_repo: HostRepository, alert_repo: AlertRepository, address: str = "10.0.0.1"
) -> int:
    host = await host_repo.create(address=address)
    alert = SecurityAlert(
        target=_TARGET,
        port=443,
        alert_type=AlertType.NEW_OPEN_PORT,
        severity=Severity.HIGH,
        message="TCP port 443 opened",
        timestamp=_NOW,
        source_event_type="port_opened",
    )
    rec = await alert_repo.create(
        host_id=host.id,
        scan_id=None,
        monitoring_event_id=None,
        alert=alert,
    )
    return rec.id


class TestNotificationDeliveryRepositoryPg:
    async def test_create_and_get_by_id(
        self,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        alert_repo = AlertRepository(pg_session)
        delivery_repo = NotificationDeliveryRepository(pg_session)

        alert_id = await _make_alert_record(host_repo, alert_repo, "10.0.0.2")

        record = await delivery_repo.create(
            alert_id=alert_id,
            channel="webhook",
            notification_id="notif-101",
            success=True,
            delivered_at=_NOW,
            error_message=None,
        )

        record_id = record.id
        pg_session.expire_all()
        fetched = await delivery_repo.get_by_id(record_id)

        assert fetched is not None
        assert fetched.id == record.id
        assert fetched.alert_id == alert_id
        assert fetched.channel == "webhook"
        assert fetched.notification_id == "notif-101"
        assert fetched.success is True
        assert fetched.delivered_at == _NOW
        assert fetched.error_message is None
        assert fetched.created_at is not None

    async def test_create_from_result_failure(
        self,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        alert_repo = AlertRepository(pg_session)
        delivery_repo = NotificationDeliveryRepository(pg_session)

        alert_id = await _make_alert_record(host_repo, alert_repo, "10.0.0.3")

        result = DeliveryResult(
            success=False,
            channel=NotificationChannel.WEBHOOK,
            notification_id="fail-101",
            delivered_at=None,
            error_message="HTTP 502 Bad Gateway",
        )

        record = await delivery_repo.create_from_result(
            alert_id=alert_id, result=result
        )

        record_id = record.id
        pg_session.expire_all()
        fetched = await delivery_repo.get_by_id(record_id)

        assert fetched is not None
        assert fetched.success is False
        assert fetched.error_message == "HTTP 502 Bad Gateway"

    async def test_create_many_from_results(
        self,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        alert_repo = AlertRepository(pg_session)
        delivery_repo = NotificationDeliveryRepository(pg_session)

        alert_id = await _make_alert_record(host_repo, alert_repo, "10.0.0.4")

        r1 = DeliveryResult(
            success=True,
            channel=NotificationChannel.WEBHOOK,
            notification_id="b1",
            delivered_at=_NOW,
        )
        r2 = DeliveryResult(
            success=False,
            channel=NotificationChannel.WEBHOOK,
            notification_id="b2",
            error_message="Timeout",
        )

        records = await delivery_repo.create_many_from_results(
            [(alert_id, r1), (alert_id, r2)]
        )
        assert len(records) == 2

        deliveries = await delivery_repo.list_by_alert(alert_id)
        assert len(deliveries) == 2

    async def test_list_recent(
        self,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        alert_repo = AlertRepository(pg_session)
        delivery_repo = NotificationDeliveryRepository(pg_session)

        alert_id = await _make_alert_record(host_repo, alert_repo, "10.0.0.5")

        for i in range(3):
            await delivery_repo.create(
                alert_id=alert_id,
                channel="webhook",
                notification_id=f"rec-{i}",
                success=True,
                delivered_at=_NOW,
            )

        recent = await delivery_repo.list_recent(limit=2)
        assert len(recent) == 2

    async def test_count_by_alerts(
        self,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        alert_repo = AlertRepository(pg_session)
        delivery_repo = NotificationDeliveryRepository(pg_session)

        a1 = await _make_alert_record(host_repo, alert_repo, "10.0.0.6")
        a2 = await _make_alert_record(host_repo, alert_repo, "10.0.0.7")

        await delivery_repo.create(
            alert_id=a1, channel="webhook", notification_id="c1", success=True
        )
        await delivery_repo.create(
            alert_id=a1, channel="webhook", notification_id="c2", success=False
        )
        await delivery_repo.create(
            alert_id=a2, channel="webhook", notification_id="c3", success=True
        )

        counts = await delivery_repo.count_by_alerts([a1, a2, 99999])
        assert counts[a1] == 2
        assert counts[a2] == 1
        assert counts[99999] == 0

    async def test_fk_constraint_rejects_nonexistent_alert(
        self,
        pg_session: AsyncSession,
    ) -> None:
        delivery_repo = NotificationDeliveryRepository(pg_session)

        with pytest.raises(IntegrityError):
            await delivery_repo.create(
                alert_id=999999,
                channel="webhook",
                notification_id="invalid-fk",
                success=True,
            )
