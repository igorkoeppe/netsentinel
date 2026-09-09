"""NotificationDeliveryService — orchestrates alert delivery and persistence."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from app.detection.alerts import SecurityAlert
from app.notifications.models import (
    DeliveryResult,
    Notification,
    NotificationChannel,
)
from app.notifications.policy import (
    DEFAULT_NOTIFICATION_POLICY,
    NotificationPolicy,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.security_alert import SecurityAlertRecord
    from app.notifications.sender import NotificationSender
    from app.repositories.notification_delivery import NotificationDeliveryRepository

logger = logging.getLogger(__name__)


class NotificationDeliveryService:
    """Orchestrates security alert delivery through configured senders and policy.

    Flow:
    1. Evaluates alert against NotificationPolicy (severity >= threshold).
    2. Constructs a Notification from the alert.
    3. Asynchronously sends via the configured sender (e.g. WebhookNotificationSender).
    4. Persists the DeliveryResult to PostgreSQL via NotificationDeliveryRepository
       if a database session is provided.

    Parameters
    ----------
    session:
        Optional active AsyncSession. When provided with an alert_id, delivery
        results are persisted to the database.
    policy:
        NotificationPolicy controlling the minimum severity threshold. Defaults
        to DEFAULT_NOTIFICATION_POLICY (HIGH).
    sender:
        NotificationSender or NotificationDispatcher instance responsible for
        actual network/I/O delivery.
    delivery_repo:
        Optional pre-instantiated NotificationDeliveryRepository.
    """

    def __init__(
        self,
        session: AsyncSession | None = None,
        *,
        policy: NotificationPolicy | None = None,
        sender: NotificationSender | Any | None = None,
        delivery_repo: NotificationDeliveryRepository | None = None,
    ) -> None:
        self._session = session
        self.policy = policy if policy is not None else DEFAULT_NOTIFICATION_POLICY
        self.sender = sender
        if delivery_repo is not None:
            self._delivery_repo: NotificationDeliveryRepository | None = delivery_repo
        elif session is not None:
            from app.repositories.notification_delivery import (
                NotificationDeliveryRepository,
            )

            self._delivery_repo = NotificationDeliveryRepository(session)
        else:
            self._delivery_repo = None

    async def deliver_alert(
        self,
        alert: SecurityAlert,
        *,
        alert_id: int | None = None,
        channel: NotificationChannel = NotificationChannel.WEBHOOK,
    ) -> DeliveryResult | None:
        """Evaluate an alert and deliver it through the configured sender if eligible.

        Parameters
        ----------
        alert:
            The domain SecurityAlert to evaluate and deliver.
        alert_id:
            Optional primary key of the persisted SecurityAlertRecord. Required
            for database persistence of the delivery result.
        channel:
            Target notification channel (default: WEBHOOK).

        Returns
        -------
        DeliveryResult | None:
            The delivery outcome, or None if the alert did not meet the policy
            threshold or if no sender was configured.
        """
        if not self.policy.should_notify(alert):
            logger.debug(
                "Alert %s (%s) below minimum severity %s — skipping notification",
                alert.alert_type,
                alert.severity,
                self.policy.minimum_severity,
            )
            return None

        if self.sender is None:
            logger.debug("No notification sender configured — skipping delivery")
            return None

        extra_meta: dict[str, Any] = {}
        if alert_id is not None:
            extra_meta["alert_id"] = alert_id

        notification = Notification.from_alert(
            alert,
            channel=channel,
            extra_metadata=extra_meta if extra_meta else None,
        )

        try:
            result: DeliveryResult = await self.sender.send(notification)
        except Exception as exc:
            logger.error(
                "Unhandled exception in notification sender for alert %s: %s",
                alert_id or alert.alert_type,
                exc,
                exc_info=True,
            )
            result = DeliveryResult(
                success=False,
                channel=channel,
                notification_id=notification.id,
                error_message=f"Sender failure: {exc}",
            )

        # Persist to database if session and alert_id are available
        if (
            self._session is not None
            and alert_id is not None
            and self._delivery_repo is not None
        ):
            try:
                await self._delivery_repo.create_from_result(
                    alert_id=alert_id,
                    result=result,
                )
                await self._session.commit()
                logger.debug(
                    "Persisted delivery result for alert_id=%s success=%s",
                    alert_id,
                    result.success,
                )
            except Exception as exc:
                logger.error(
                    "Failed to persist notification delivery record for alert %s: %s",
                    alert_id,
                    exc,
                )
                await self._session.rollback()
                raise

        return result

    async def deliver_alerts(
        self,
        alerts: Sequence[SecurityAlert],
        alert_records: Sequence[SecurityAlertRecord] | None = None,
        *,
        channel: NotificationChannel = NotificationChannel.WEBHOOK,
    ) -> list[DeliveryResult]:
        """Deliver a batch of security alerts, matching with ORM records if provided.

        Parameters
        ----------
        alerts:
            Sequence of SecurityAlert domain objects.
        alert_records:
            Optional matching sequence of SecurityAlertRecords (for alert IDs).

        Returns
        -------
        list[DeliveryResult]:
            List of delivery results for all alerts that met the notification threshold.
        """
        results: list[DeliveryResult] = []

        if alert_records is not None:
            for alert, record in zip(alerts, alert_records, strict=False):
                res = await self.deliver_alert(
                    alert,
                    alert_id=record.id,
                    channel=channel,
                )
                if res is not None:
                    results.append(res)
        else:
            for alert in alerts:
                res = await self.deliver_alert(
                    alert,
                    alert_id=None,
                    channel=channel,
                )
                if res is not None:
                    results.append(res)

        return results
