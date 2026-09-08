"""Security alert domain model.

A SecurityAlert is an *interpretation* of a MonitoringEvent, not the event
itself.  Events record observed facts (e.g. "port 443 went from CLOSED to
OPEN"); alerts assign defensive meaning ("new open port detected, severity
HIGH").

This module defines pure data and lifecycle domain logic — no persistence,
no notifications, no side-effects.
"""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
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


class AlertStatus(StrEnum):
    """Lifecycle triage status of a security alert."""

    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class InvalidAlertStateTransitionError(ValueError):
    """Raised when an invalid alert state transition is attempted."""

    def __init__(
        self,
        current_status: AlertStatus,
        target_status: AlertStatus,
        message: str | None = None,
    ) -> None:
        self.current_status = current_status
        self.target_status = target_status
        msg = message or (
            f"Cannot transition alert from {current_status.value} to"
            f" {target_status.value}."
        )
        super().__init__(msg)


# Domain alias for backward/forward naming compatibility
InvalidAlertTransitionError = InvalidAlertStateTransitionError


def _to_comparable_dt(dt: datetime) -> datetime:
    """Normalize datetime for offset-naive vs offset-aware comparison."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


@dataclass(frozen=True)
class AlertLifecycle:
    """Triage lifecycle state and timestamps of a security alert."""

    status: AlertStatus = AlertStatus.OPEN
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None

    def __post_init__(self) -> None:
        if (
            self.acknowledged_at is not None
            and self.resolved_at is not None
            and _to_comparable_dt(self.resolved_at)
            < _to_comparable_dt(self.acknowledged_at)
        ):
            raise ValueError(
                f"resolved_at ({self.resolved_at}) cannot be earlier "
                f"than acknowledged_at ({self.acknowledged_at})."
            )

    @property
    def is_open(self) -> bool:
        """Return True if the lifecycle is in OPEN status."""
        return self.status == AlertStatus.OPEN

    @property
    def is_acknowledged(self) -> bool:
        """Return True if the lifecycle is in ACKNOWLEDGED status."""
        return self.status == AlertStatus.ACKNOWLEDGED

    @property
    def is_resolved(self) -> bool:
        """Return True if the lifecycle is in RESOLVED status."""
        return self.status == AlertStatus.RESOLVED

    def transition_to(
        self,
        target_status: AlertStatus,
        *,
        at: datetime | None = None,
    ) -> "AlertLifecycle":
        """Transition to a new status, returning a new immutable instance."""
        if target_status == self.status:
            raise InvalidAlertStateTransitionError(
                self.status,
                target_status,
                f"Alert is already in {self.status.value} status.",
            )

        now = at if at is not None else datetime.now(UTC)

        match (self.status, target_status):
            case (AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED):
                return replace(
                    self,
                    status=AlertStatus.ACKNOWLEDGED,
                    acknowledged_at=now,
                )
            case (AlertStatus.OPEN, AlertStatus.RESOLVED):
                return replace(
                    self,
                    status=AlertStatus.RESOLVED,
                    resolved_at=now,
                )
            case (AlertStatus.ACKNOWLEDGED, AlertStatus.RESOLVED):
                return replace(
                    self,
                    status=AlertStatus.RESOLVED,
                    resolved_at=now,
                )
            case (AlertStatus.ACKNOWLEDGED, AlertStatus.OPEN):
                return replace(
                    self,
                    status=AlertStatus.OPEN,
                    acknowledged_at=None,
                )
            case (AlertStatus.RESOLVED, AlertStatus.OPEN):
                return replace(
                    self,
                    status=AlertStatus.OPEN,
                    acknowledged_at=None,
                    resolved_at=None,
                )
            case _:
                raise InvalidAlertStateTransitionError(
                    self.status,
                    target_status,
                )

    def acknowledge(self, *, at: datetime | None = None) -> "AlertLifecycle":
        """Acknowledge the alert, marking it under active investigation."""
        return self.transition_to(AlertStatus.ACKNOWLEDGED, at=at)

    def resolve(self, *, at: datetime | None = None) -> "AlertLifecycle":
        """Resolve the alert, marking the underlying issue as addressed."""
        return self.transition_to(AlertStatus.RESOLVED, at=at)

    def reopen(self, *, at: datetime | None = None) -> "AlertLifecycle":
        """Reopen a resolved alert, resetting it back to OPEN status."""
        return self.transition_to(AlertStatus.OPEN, at=at)

    def unacknowledge(self) -> "AlertLifecycle":
        """Return an acknowledged alert back to the OPEN triage queue."""
        return self.transition_to(AlertStatus.OPEN)


def acknowledge_alert(
    lifecycle: AlertLifecycle,
    *,
    at: datetime | None = None,
) -> AlertLifecycle:
    """Domain transition helper to acknowledge an alert lifecycle."""
    return lifecycle.acknowledge(at=at)


def resolve_alert(
    lifecycle: AlertLifecycle,
    *,
    at: datetime | None = None,
) -> AlertLifecycle:
    """Domain transition helper to resolve an alert lifecycle."""
    return lifecycle.resolve(at=at)


def reopen_alert(
    lifecycle: AlertLifecycle,
    *,
    at: datetime | None = None,
) -> AlertLifecycle:
    """Domain transition helper to reopen an alert lifecycle."""
    return lifecycle.reopen(at=at)


def unacknowledge_alert(
    lifecycle: AlertLifecycle,
) -> AlertLifecycle:
    """Domain transition helper to unacknowledge an alert lifecycle."""
    return lifecycle.unacknowledge()


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
        status: The triage lifecycle status of the alert (default: OPEN).
        acknowledged_at: When the alert was acknowledged by an analyst.
        resolved_at: When the alert was resolved.
    """

    alert_type: AlertType
    severity: Severity
    target: NetworkTarget
    timestamp: datetime
    message: str
    port: int | None
    source_event_type: str
    status: AlertStatus = AlertStatus.OPEN
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.acknowledged_at is not None:
            if _to_comparable_dt(self.acknowledged_at) < _to_comparable_dt(
                self.timestamp
            ):
                raise ValueError(
                    f"acknowledged_at ({self.acknowledged_at}) cannot be earlier "
                    f"than alert timestamp ({self.timestamp})."
                )

        if self.resolved_at is not None:
            if _to_comparable_dt(self.resolved_at) < _to_comparable_dt(self.timestamp):
                raise ValueError(
                    f"resolved_at ({self.resolved_at}) cannot be earlier "
                    f"than alert timestamp ({self.timestamp})."
                )
            if self.acknowledged_at is not None and _to_comparable_dt(
                self.resolved_at
            ) < _to_comparable_dt(self.acknowledged_at):
                raise ValueError(
                    f"resolved_at ({self.resolved_at}) cannot be earlier "
                    f"than acknowledged_at ({self.acknowledged_at})."
                )

    @property
    def lifecycle(self) -> AlertLifecycle:
        """Return the current AlertLifecycle value object for this alert."""
        return AlertLifecycle(
            status=self.status,
            acknowledged_at=self.acknowledged_at,
            resolved_at=self.resolved_at,
        )

    @property
    def is_open(self) -> bool:
        """Return True if the alert is in OPEN status."""
        return self.status == AlertStatus.OPEN

    @property
    def is_acknowledged(self) -> bool:
        """Return True if the alert is in ACKNOWLEDGED status."""
        return self.status == AlertStatus.ACKNOWLEDGED

    @property
    def is_resolved(self) -> bool:
        """Return True if the alert is in RESOLVED status."""
        return self.status == AlertStatus.RESOLVED

    def transition_to(
        self,
        target_status: AlertStatus,
        *,
        at: datetime | None = None,
    ) -> "SecurityAlert":
        """Transition the alert to a new status, returning a new immutable instance.

        Raises:
            InvalidAlertStateTransitionError: If the transition is not allowed.
            ValueError: If the transition timestamp violates chronological ordering.
        """
        new_lifecycle = self.lifecycle.transition_to(target_status, at=at)
        return replace(
            self,
            status=new_lifecycle.status,
            acknowledged_at=new_lifecycle.acknowledged_at,
            resolved_at=new_lifecycle.resolved_at,
        )

    def acknowledge(self, *, at: datetime | None = None) -> "SecurityAlert":
        """Acknowledge the alert, marking it under active investigation."""
        return self.transition_to(AlertStatus.ACKNOWLEDGED, at=at)

    def resolve(self, *, at: datetime | None = None) -> "SecurityAlert":
        """Resolve the alert, marking the underlying issue as addressed."""
        return self.transition_to(AlertStatus.RESOLVED, at=at)

    def reopen(self, *, at: datetime | None = None) -> "SecurityAlert":
        """Reopen a resolved alert, resetting it back to OPEN status."""
        return self.transition_to(AlertStatus.OPEN, at=at)

    def unacknowledge(self) -> "SecurityAlert":
        """Return an acknowledged alert back to the OPEN triage queue."""
        return self.transition_to(AlertStatus.OPEN)
