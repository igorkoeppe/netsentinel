"""Detection rules that convert MonitoringEvents into SecurityAlerts.

Each rule is a small function that receives a single MonitoringEvent and returns
a SecurityAlert.  Rules are intentionally kept simple — no abstract base
classes, no plugin loaders, no registry factories.

The mapping table ``_RULES`` connects each MonitoringEventType to its
evaluation function.  Unknown event types are silently ignored (no alert
generated, no crash).
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.detection.alerts import AlertType, SecurityAlert, Severity
from app.detection.engine import MonitoringEvent, MonitoringEventType


@dataclass(frozen=True)
class AlertPolicy:
    """Configurable severity and expected ports policy for alert generation rules.

    Pure, immutable dataclass containing the severities to assign to each
    generated alert type, plus optional expected TCP ports configuration.
    Default values preserve existing NetSentinel behavior.
    """

    new_open_port_severity: Severity = Severity.HIGH
    port_closed_severity: Severity = Severity.LOW
    host_down_severity: Severity = Severity.MEDIUM
    host_recovered_severity: Severity = Severity.INFO
    expected_tcp_ports: frozenset[int] | None = None
    expected_open_port_severity: Severity = Severity.INFO
    unexpected_open_port_severity: Severity = Severity.HIGH


DEFAULT_ALERT_POLICY = AlertPolicy()


def _evaluate_port_opened(
    event: MonitoringEvent,
    policy: AlertPolicy,
) -> SecurityAlert:
    """A port transitioning to OPEN may indicate an expanded attack surface."""
    if policy.expected_tcp_ports is not None:
        if event.port is not None and event.port in policy.expected_tcp_ports:
            return SecurityAlert(
                alert_type=AlertType.EXPECTED_OPEN_PORT,
                severity=policy.expected_open_port_severity,
                target=event.target,
                timestamp=event.timestamp,
                message=(
                    f"Expected TCP port {event.port} became open on"
                    f" {event.target.value}."
                ),
                port=event.port,
                source_event_type=event.event_type.value,
            )
        return SecurityAlert(
            alert_type=AlertType.UNEXPECTED_OPEN_PORT,
            severity=policy.unexpected_open_port_severity,
            target=event.target,
            timestamp=event.timestamp,
            message=(
                f"Unexpected TCP port {event.port} became open on {event.target.value}."
            ),
            port=event.port,
            source_event_type=event.event_type.value,
        )

    return SecurityAlert(
        alert_type=AlertType.NEW_OPEN_PORT,
        severity=policy.new_open_port_severity,
        target=event.target,
        timestamp=event.timestamp,
        message=f"New TCP port {event.port} detected on {event.target.value}.",
        port=event.port,
        source_event_type=event.event_type.value,
    )


def _evaluate_port_closed(
    event: MonitoringEvent,
    policy: AlertPolicy,
) -> SecurityAlert:
    """A port transitioning to CLOSED may indicate a configuration change."""
    return SecurityAlert(
        alert_type=AlertType.PORT_CLOSED,
        severity=policy.port_closed_severity,
        target=event.target,
        timestamp=event.timestamp,
        message=f"TCP port {event.port} closed on {event.target.value}.",
        port=event.port,
        source_event_type=event.event_type.value,
    )


def _evaluate_host_became_unavailable(
    event: MonitoringEvent,
    policy: AlertPolicy,
) -> SecurityAlert:
    """Host stopped responding — possible outage or network issue."""
    return SecurityAlert(
        alert_type=AlertType.HOST_DOWN,
        severity=policy.host_down_severity,
        target=event.target,
        timestamp=event.timestamp,
        message=f"Host {event.target.value} became unavailable.",
        port=None,
        source_event_type=event.event_type.value,
    )


def _evaluate_host_became_available(
    event: MonitoringEvent,
    policy: AlertPolicy,
) -> SecurityAlert:
    """Host is responding again after being unavailable."""
    return SecurityAlert(
        alert_type=AlertType.HOST_RECOVERED,
        severity=policy.host_recovered_severity,
        target=event.target,
        timestamp=event.timestamp,
        message=f"Host {event.target.value} is available again.",
        port=None,
        source_event_type=event.event_type.value,
    )


# ---------------------------------------------------------------------------
# Rule dispatch table
# ---------------------------------------------------------------------------

_RuleFunction = Callable[[MonitoringEvent, AlertPolicy], SecurityAlert]

_RULES: dict[MonitoringEventType, _RuleFunction] = {
    MonitoringEventType.PORT_OPENED: _evaluate_port_opened,
    MonitoringEventType.PORT_CLOSED: _evaluate_port_closed,
    MonitoringEventType.HOST_BECAME_UNAVAILABLE: _evaluate_host_became_unavailable,
    MonitoringEventType.HOST_BECAME_AVAILABLE: _evaluate_host_became_available,
}


def evaluate_event(
    event: MonitoringEvent,
    policy: AlertPolicy = DEFAULT_ALERT_POLICY,
) -> SecurityAlert | None:
    """Evaluate a single event against known rules using the given policy.

    Returns a SecurityAlert if a matching rule exists, or None if the event
    type is not yet covered by any rule.
    """
    rule_fn = _RULES.get(event.event_type)
    if rule_fn is None:
        return None
    return rule_fn(event, policy)


def generate_alerts(
    events: list[MonitoringEvent],
    policy: AlertPolicy = DEFAULT_ALERT_POLICY,
) -> list[SecurityAlert]:
    """Convert a list of monitoring events into security alerts.

    This is the main entry point of the Alert Engine.  It is a pure,
    deterministic function: same input always produces same output.

    - Preserves input order: alerts appear in the same sequence as their
      source events.
    - Events without a matching rule are silently skipped.
    - An empty input list produces an empty output list.
    - Severities are determined by the provided policy (defaults to
      DEFAULT_ALERT_POLICY).

    This function does NOT compare snapshots, execute scans, or access any
    database.
    """
    alerts: list[SecurityAlert] = []
    for event in events:
        alert = evaluate_event(event, policy=policy)
        if alert is not None:
            alerts.append(alert)
    return alerts
