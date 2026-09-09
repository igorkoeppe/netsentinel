"""Domain models for NetSentinel alert notifications.

Defines the Notification value object, supported delivery channels, and delivery
results. All models are pure data structures with no side effects.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.detection.alerts import SecurityAlert


class NotificationChannel(StrEnum):
    """Delivery channel for security alert notifications."""

    CONSOLE = "console"
    LOG = "log"
    WEBHOOK = "webhook"
    IN_MEMORY = "in_memory"


@dataclass(frozen=True)
class NotificationResult:
    """Outcome of attempting to deliver a notification through a channel."""

    success: bool
    channel: NotificationChannel
    notification_id: str
    delivered_at: datetime | None = None
    error_message: str | None = None


# Alias for backward/forward naming compatibility
DeliveryResult = NotificationResult


@dataclass(frozen=True)
class Notification:
    """A formatted message dispatched to a delivery channel from a SecurityAlert.

    Attributes:
        id: Unique identifier for the notification.
        alert_type: Type of the source alert (e.g., 'new_open_port').
        severity: Severity level ('info', 'low', 'medium', 'high', 'critical').
        target_address: String representation of the target host.
        title: Short summary title of the notification.
        message: Detailed description of the security event.
        channel: The channel targeted by this notification.
        timestamp: Time the underlying event occurred.
        port: TCP port if applicable to the alert.
        metadata: Supplementary contextual data.
    """

    id: str
    alert_type: str
    severity: str
    target_address: str
    title: str
    message: str
    channel: NotificationChannel
    timestamp: datetime
    port: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_alert(
        cls,
        alert: SecurityAlert,
        channel: NotificationChannel,
        *,
        title: str | None = None,
        notification_id: str | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> Notification:
        """Construct a Notification from a domain SecurityAlert.

        Parameters:
            alert: The source SecurityAlert.
            channel: Target notification channel.
            title: Optional custom title override.
            notification_id: Optional custom notification id.
            extra_metadata: Optional additional metadata fields to merge.
        """
        severity_label = alert.severity.value.upper()
        type_label = alert.alert_type.value.replace("_", " ").title()
        generated_title = (
            title or f"[{severity_label}] {type_label} on {alert.target.value}"
        )

        merged_metadata: dict[str, Any] = {
            "source_event_type": alert.source_event_type,
            "status": alert.status.value,
        }
        if extra_metadata:
            merged_metadata.update(extra_metadata)

        ts = (
            alert.timestamp
            if alert.timestamp.tzinfo is not None
            else alert.timestamp.replace(tzinfo=UTC)
        )

        return cls(
            id=notification_id or uuid.uuid4().hex,
            alert_type=alert.alert_type.value,
            severity=alert.severity.value,
            target_address=alert.target.value,
            title=generated_title,
            message=alert.message,
            channel=channel,
            timestamp=ts,
            port=alert.port,
            metadata=merged_metadata,
        )
