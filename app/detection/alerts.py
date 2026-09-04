"""Security alert domain model.

A SecurityAlert is an *interpretation* of a MonitoringEvent, not the event
itself.  Events record observed facts (e.g. "port 443 went from CLOSED to
OPEN"); alerts assign defensive meaning ("new open port detected, severity
HIGH").

This module defines only pure data — no persistence, no notifications, no
side-effects.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.monitoring.target import NetworkTarget


class AlertType(StrEnum):
    """Classification of a security alert."""

    NEW_OPEN_PORT = "new_open_port"
    PORT_CLOSED = "port_closed"
    HOST_DOWN = "host_down"
    HOST_RECOVERED = "host_recovered"
    EXPECTED_OPEN_PORT = "expected_open_port"
    UNEXPECTED_OPEN_PORT = "unexpected_open_port"


class Severity(StrEnum):
    """Alert severity level, ordered from least to most severe."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class SecurityAlert:
    """A security-relevant interpretation of a monitoring event.

    Attributes:
        alert_type: The classification of this alert.
        severity: How important the alert is from a defensive standpoint.
        target: The network target associated with the alert.
        timestamp: When the underlying change was *observed* (from the event).
        message: Human-readable description of what happened.
        port: TCP port number, if applicable. ``None`` for host-level alerts.
        source_event_type: The MonitoringEventType string that produced this
            alert, for traceability.
    """

    alert_type: AlertType
    severity: Severity
    target: NetworkTarget
    timestamp: datetime
    message: str
    port: int | None
    source_event_type: str
