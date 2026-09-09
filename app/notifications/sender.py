"""Notification sender interfaces and standard implementations.

Provides the NotificationSender protocol and concrete senders for in-memory,
logging, and console outputs.
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime
from typing import Protocol, TextIO

from app.notifications.models import (
    Notification,
    NotificationChannel,
    NotificationResult,
)


class NotificationSender(Protocol):
    """Protocol defining the asynchronous delivery interface for notifications."""

    async def send(self, notification: Notification) -> NotificationResult:
        """Asynchronously send a notification.

        Parameters:
            notification: The notification object to send.

        Returns:
            NotificationResult representing the outcome of the delivery.
        """
        ...


class InMemoryNotificationSender:
    """In-memory notification sender for testing and deterministic inspection."""

    def __init__(self) -> None:
        self.notifications: list[Notification] = []
        self.results: list[NotificationResult] = []

    async def send(self, notification: Notification) -> NotificationResult:
        """Store the notification in memory and return a successful result."""
        self.notifications.append(notification)
        result = NotificationResult(
            success=True,
            channel=NotificationChannel.IN_MEMORY,
            notification_id=notification.id,
            delivered_at=datetime.now(UTC),
        )
        self.results.append(result)
        return result

    def clear(self) -> None:
        """Clear all stored notifications and results."""
        self.notifications.clear()
        self.results.clear()

    @property
    def count(self) -> int:
        """Return the number of notifications received."""
        return len(self.notifications)


class LoggingNotificationSender:
    """Delivers notifications to Python's standard logging subsystem.

    Maps alert severities to appropriate logging levels:
    - critical -> logging.CRITICAL
    - high -> logging.ERROR
    - medium -> logging.WARNING
    - low, info -> logging.INFO
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("netsentinel.notifications")

    async def send(self, notification: Notification) -> NotificationResult:
        """Format and log the notification according to its severity level."""
        log_msg = (
            f"[{notification.severity.upper()}] {notification.title} - "
            f"{notification.message} (target: {notification.target_address}, "
            f"port: {notification.port})"
        )

        match notification.severity.lower():
            case "critical":
                self._logger.critical(log_msg)
            case "high":
                self._logger.error(log_msg)
            case "medium":
                self._logger.warning(log_msg)
            case _:
                self._logger.info(log_msg)

        return NotificationResult(
            success=True,
            channel=NotificationChannel.LOG,
            notification_id=notification.id,
            delivered_at=datetime.now(UTC),
        )


class ConsoleNotificationSender:
    """Outputs human-readable security notifications to a console stream (stdout)."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream if stream is not None else sys.stdout

    async def send(self, notification: Notification) -> NotificationResult:
        """Format and write the notification to the target text stream."""
        separator = "=" * 55
        port_info = f":{notification.port}" if notification.port is not None else ""
        text = (
            f"\n{separator}\n"
            f"[SECURITY ALERT] {notification.severity.upper()}\n"
            f"Title:   {notification.title}\n"
            f"Target:  {notification.target_address}{port_info}\n"
            f"Type:    {notification.alert_type}\n"
            f"Time:    {notification.timestamp.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
            f"Message: {notification.message}\n"
            f"{separator}\n"
        )
        self._stream.write(text)
        self._stream.flush()

        return NotificationResult(
            success=True,
            channel=NotificationChannel.CONSOLE,
            notification_id=notification.id,
            delivered_at=datetime.now(UTC),
        )
