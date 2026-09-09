"""Notification dispatcher for routing SecurityAlerts to configured channels.

Orchestrates conversion of SecurityAlerts to Notifications and fans out delivery
to all registered NotificationSender instances concurrently and resiliently.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from app.detection.alerts import SecurityAlert
from app.notifications.models import (
    Notification,
    NotificationChannel,
    NotificationResult,
)
from app.notifications.sender import NotificationSender

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    """Orchestrates fan-out delivery of security alerts across notification channels.

    Example:
        dispatcher = NotificationDispatcher()
        dispatcher.register(NotificationChannel.LOG, LoggingNotificationSender())
        dispatcher.register(NotificationChannel.CONSOLE, ConsoleNotificationSender())

        results = await dispatcher.dispatch(alert)
    """

    def __init__(self) -> None:
        self._senders: dict[NotificationChannel, list[NotificationSender]] = {}

    def register(
        self,
        channel: NotificationChannel,
        sender: NotificationSender,
    ) -> None:
        """Register a sender for a notification channel.

        Multiple senders can be registered for the same channel.
        """
        if channel not in self._senders:
            self._senders[channel] = []
        self._senders[channel].append(sender)

    def unregister(self, channel: NotificationChannel) -> None:
        """Remove all senders registered for a given channel."""
        self._senders.pop(channel, None)

    @property
    def registered_channels(self) -> list[NotificationChannel]:
        """Return the list of channels that have registered senders."""
        return list(self._senders.keys())

    async def _dispatch_single(
        self,
        sender: NotificationSender,
        notification: Notification,
    ) -> NotificationResult:
        """Safely execute a single sender with exception isolation."""
        try:
            return await sender.send(notification)
        except Exception as exc:
            logger.error(
                "Unhandled exception in notification sender %s for alert %s: %s",
                sender.__class__.__name__,
                notification.id,
                exc,
                exc_info=True,
            )
            return NotificationResult(
                success=False,
                channel=notification.channel,
                notification_id=notification.id,
                error_message=f"Sender failure: {exc}",
            )

    async def dispatch(
        self,
        alert: SecurityAlert,
        channels: Sequence[NotificationChannel] | None = None,
    ) -> list[NotificationResult]:
        """Convert a SecurityAlert into Notifications and dispatch to target channels.

        Parameters:
            alert: The security alert to deliver.
            channels: Specific channels to target. If None, targets all
                currently registered channels.

        Returns:
            List of NotificationResult objects for each attempted delivery.
        """
        target_channels = (
            list(channels) if channels is not None else self.registered_channels
        )

        tasks: list[asyncio.Task[NotificationResult]] = []
        for channel in target_channels:
            senders = self._senders.get(channel, [])
            if not senders:
                continue

            notification = Notification.from_alert(alert, channel)
            for sender in senders:
                tasks.append(
                    asyncio.create_task(self._dispatch_single(sender, notification))
                )

        if not tasks:
            return []

        results = await asyncio.gather(*tasks)
        return list(results)

    async def dispatch_many(
        self,
        alerts: Sequence[SecurityAlert],
        channels: Sequence[NotificationChannel] | None = None,
    ) -> list[NotificationResult]:
        """Dispatch a sequence of SecurityAlerts across channels.

        Parameters:
            alerts: Sequence of security alerts to deliver.
            channels: Specific channels to target (defaults to all registered).

        Returns:
            Aggregated list of NotificationResults across all alerts.
        """
        all_results: list[NotificationResult] = []
        for alert in alerts:
            results = await self.dispatch(alert, channels=channels)
            all_results.extend(results)
        return all_results
