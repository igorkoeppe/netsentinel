"""Notification policy determining if a SecurityAlert triggers a Notification.

The policy evaluates whether an alert's severity meets or exceeds a configured
minimum severity threshold. It is a pure domain component without side-effects,
I/O, or dependencies on external systems.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.detection.alerts import SecurityAlert, Severity
from app.notifications.models import Notification, NotificationChannel

# Explicit numeric ordering for severity comparison (avoids alphabetical order)
SEVERITY_ORDER: dict[Severity, int] = {
    Severity.INFO: 10,
    Severity.LOW: 20,
    Severity.MEDIUM: 30,
    Severity.HIGH: 40,
    Severity.CRITICAL: 50,
}


@dataclass(frozen=True)
class NotificationPolicy:
    """Configurable policy controlling alert notification generation.

    Attributes:
        minimum_severity: Minimum alert severity required to trigger a notification.
            Defaults to Severity.HIGH (conservative default: HIGH and CRITICAL notify).
    """

    minimum_severity: Severity = Severity.HIGH

    def should_notify(self, alert: SecurityAlert) -> bool:
        """Determine whether a SecurityAlert meets the minimum severity threshold.

        Decision is strictly based on whether alert.severity >= minimum_severity.
        Neither alert_type, status/lifecycle, target, nor port influence the decision.
        """
        return SEVERITY_ORDER[alert.severity] >= SEVERITY_ORDER[self.minimum_severity]


DEFAULT_NOTIFICATION_POLICY = NotificationPolicy()


def should_notify(
    alert: SecurityAlert,
    policy: NotificationPolicy | None = None,
) -> bool:
    """Evaluate whether an alert should generate a notification under a given policy.

    Parameters:
        alert: The SecurityAlert to evaluate.
        policy: The NotificationPolicy to use (defaults to DEFAULT_NOTIFICATION_POLICY).

    Returns:
        True if alert severity meets or exceeds the policy's threshold.
    """
    pol = policy if policy is not None else DEFAULT_NOTIFICATION_POLICY
    return pol.should_notify(alert)


def notification_for_alert(
    alert: SecurityAlert,
    policy: NotificationPolicy,
    channel: NotificationChannel = NotificationChannel.CONSOLE,
) -> Notification | None:
    """Construct a Notification if the alert meets the policy threshold, else None.

    Semantics:
        policy.should_notify(alert) is True  -> Notification.from_alert(alert, channel)
        policy.should_notify(alert) is False -> None
    """
    if not policy.should_notify(alert):
        return None
    return Notification.from_alert(alert, channel)
