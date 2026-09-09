"""Notification subsystem for NetSentinel security alerts.

Exposes the Notification domain model, delivery channels, senders, and dispatcher.
"""

from app.notifications.dispatcher import NotificationDispatcher
from app.notifications.models import (
    DeliveryResult,
    Notification,
    NotificationChannel,
    NotificationResult,
)
from app.notifications.policy import (
    DEFAULT_NOTIFICATION_POLICY,
    NotificationPolicy,
    notification_for_alert,
    should_notify,
)
from app.notifications.sender import (
    ConsoleNotificationSender,
    InMemoryNotificationSender,
    LoggingNotificationSender,
    NotificationSender,
)
from app.notifications.webhook import WebhookNotificationSender

__all__ = [
    "ConsoleNotificationSender",
    "DEFAULT_NOTIFICATION_POLICY",
    "DeliveryResult",
    "InMemoryNotificationSender",
    "LoggingNotificationSender",
    "Notification",
    "NotificationChannel",
    "NotificationDispatcher",
    "NotificationPolicy",
    "NotificationResult",
    "NotificationSender",
    "WebhookNotificationSender",
    "notification_for_alert",
    "should_notify",
]
