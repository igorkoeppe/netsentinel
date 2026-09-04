"""Unit tests for the security alert engine (v0.4.0).

All tests are pure — no PostgreSQL, Docker, sockets, asyncio, or internet.
They work exclusively with in-memory MonitoringEvent objects.
"""

from datetime import UTC, datetime

import pytest

from app.core.config import Settings, _parse_expected_tcp_ports, _parse_severity
from app.detection.alerts import AlertType, Severity
from app.detection.engine import MonitoringEvent, MonitoringEventType
from app.detection.rules import (
    DEFAULT_ALERT_POLICY,
    AlertPolicy,
    evaluate_event,
    generate_alerts,
)
from app.monitoring.target import NetworkTarget


@pytest.fixture
def target() -> NetworkTarget:
    return NetworkTarget.parse("192.168.0.10")


@pytest.fixture
def timestamp() -> datetime:
    return datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)


def _make_event(
    event_type: MonitoringEventType,
    target: NetworkTarget,
    timestamp: datetime,
    port: int | None = None,
) -> MonitoringEvent:
    """Helper to build a MonitoringEvent with sensible defaults."""
    return MonitoringEvent(
        event_type=event_type,
        target=target,
        timestamp=timestamp,
        port=port,
        previous_state="closed" if port else "available",
        current_state="open" if port else "unavailable",
    )


# -----------------------------------------------------------------------
# PORT_OPENED → NEW_OPEN_PORT / HIGH
# -----------------------------------------------------------------------
class TestPortOpenedRule:
    def test_produces_new_open_port_alert(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        event = _make_event(
            MonitoringEventType.PORT_OPENED, target, timestamp, port=443
        )
        alert = evaluate_event(event)

        assert alert is not None
        assert alert.alert_type == AlertType.NEW_OPEN_PORT
        assert alert.severity == Severity.HIGH

    def test_preserves_port(self, target: NetworkTarget, timestamp: datetime) -> None:
        event = _make_event(
            MonitoringEventType.PORT_OPENED, target, timestamp, port=8080
        )
        alert = evaluate_event(event)
        assert alert is not None
        assert alert.port == 8080

    def test_preserves_target(self, target: NetworkTarget, timestamp: datetime) -> None:
        event = _make_event(MonitoringEventType.PORT_OPENED, target, timestamp, port=22)
        alert = evaluate_event(event)
        assert alert is not None
        assert alert.target == target

    def test_preserves_timestamp(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        event = _make_event(MonitoringEventType.PORT_OPENED, target, timestamp, port=80)
        alert = evaluate_event(event)
        assert alert is not None
        assert alert.timestamp == timestamp

    def test_message_is_descriptive(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        event = _make_event(
            MonitoringEventType.PORT_OPENED, target, timestamp, port=443
        )
        alert = evaluate_event(event)
        assert alert is not None
        assert "443" in alert.message
        assert target.value in alert.message

    def test_source_event_type(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        event = _make_event(
            MonitoringEventType.PORT_OPENED, target, timestamp, port=443
        )
        alert = evaluate_event(event)
        assert alert is not None
        assert alert.source_event_type == MonitoringEventType.PORT_OPENED.value


# -----------------------------------------------------------------------
# PORT_CLOSED → PORT_CLOSED / LOW
# -----------------------------------------------------------------------
class TestPortClosedRule:
    def test_produces_port_closed_alert(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        event = _make_event(MonitoringEventType.PORT_CLOSED, target, timestamp, port=22)
        alert = evaluate_event(event)

        assert alert is not None
        assert alert.alert_type == AlertType.PORT_CLOSED
        assert alert.severity == Severity.LOW

    def test_preserves_port(self, target: NetworkTarget, timestamp: datetime) -> None:
        event = _make_event(
            MonitoringEventType.PORT_CLOSED, target, timestamp, port=3306
        )
        alert = evaluate_event(event)
        assert alert is not None
        assert alert.port == 3306

    def test_preserves_target_and_timestamp(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        event = _make_event(MonitoringEventType.PORT_CLOSED, target, timestamp, port=80)
        alert = evaluate_event(event)
        assert alert is not None
        assert alert.target == target
        assert alert.timestamp == timestamp


# -----------------------------------------------------------------------
# HOST_BECAME_UNAVAILABLE → HOST_DOWN / MEDIUM
# -----------------------------------------------------------------------
class TestHostBecameUnavailableRule:
    def test_produces_host_down_alert(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        event = _make_event(
            MonitoringEventType.HOST_BECAME_UNAVAILABLE, target, timestamp
        )
        alert = evaluate_event(event)

        assert alert is not None
        assert alert.alert_type == AlertType.HOST_DOWN
        assert alert.severity == Severity.MEDIUM

    def test_port_is_none(self, target: NetworkTarget, timestamp: datetime) -> None:
        event = _make_event(
            MonitoringEventType.HOST_BECAME_UNAVAILABLE, target, timestamp
        )
        alert = evaluate_event(event)
        assert alert is not None
        assert alert.port is None

    def test_preserves_target(self, target: NetworkTarget, timestamp: datetime) -> None:
        event = _make_event(
            MonitoringEventType.HOST_BECAME_UNAVAILABLE, target, timestamp
        )
        alert = evaluate_event(event)
        assert alert is not None
        assert alert.target == target

    def test_preserves_timestamp(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        event = _make_event(
            MonitoringEventType.HOST_BECAME_UNAVAILABLE, target, timestamp
        )
        alert = evaluate_event(event)
        assert alert is not None
        assert alert.timestamp == timestamp

    def test_message_mentions_host(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        event = _make_event(
            MonitoringEventType.HOST_BECAME_UNAVAILABLE, target, timestamp
        )
        alert = evaluate_event(event)
        assert alert is not None
        assert target.value in alert.message


# -----------------------------------------------------------------------
# HOST_BECAME_AVAILABLE → HOST_RECOVERED / INFO
# -----------------------------------------------------------------------
class TestHostBecameAvailableRule:
    def test_produces_host_recovered_alert(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        event = _make_event(
            MonitoringEventType.HOST_BECAME_AVAILABLE, target, timestamp
        )
        alert = evaluate_event(event)

        assert alert is not None
        assert alert.alert_type == AlertType.HOST_RECOVERED
        assert alert.severity == Severity.INFO

    def test_port_is_none(self, target: NetworkTarget, timestamp: datetime) -> None:
        event = _make_event(
            MonitoringEventType.HOST_BECAME_AVAILABLE, target, timestamp
        )
        alert = evaluate_event(event)
        assert alert is not None
        assert alert.port is None

    def test_preserves_target_and_timestamp(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        event = _make_event(
            MonitoringEventType.HOST_BECAME_AVAILABLE, target, timestamp
        )
        alert = evaluate_event(event)
        assert alert is not None
        assert alert.target == target
        assert alert.timestamp == timestamp


# -----------------------------------------------------------------------
# generate_alerts — empty input
# -----------------------------------------------------------------------
class TestGenerateAlertsEmpty:
    def test_empty_list_returns_empty(self) -> None:
        assert generate_alerts([]) == []


# -----------------------------------------------------------------------
# generate_alerts — multiple events
# -----------------------------------------------------------------------
class TestGenerateAlertsMultipleEvents:
    def test_three_events_produce_three_alerts(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        events = [
            _make_event(MonitoringEventType.PORT_CLOSED, target, timestamp, port=22),
            _make_event(MonitoringEventType.PORT_OPENED, target, timestamp, port=443),
            _make_event(MonitoringEventType.HOST_BECAME_UNAVAILABLE, target, timestamp),
        ]
        alerts = generate_alerts(events)

        assert len(alerts) == 3
        assert alerts[0].alert_type == AlertType.PORT_CLOSED
        assert alerts[1].alert_type == AlertType.NEW_OPEN_PORT
        assert alerts[2].alert_type == AlertType.HOST_DOWN

    def test_mixed_event_types(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        """All four event types produce their corresponding alerts."""
        events = [
            _make_event(MonitoringEventType.PORT_OPENED, target, timestamp, port=80),
            _make_event(MonitoringEventType.PORT_CLOSED, target, timestamp, port=22),
            _make_event(MonitoringEventType.HOST_BECAME_UNAVAILABLE, target, timestamp),
            _make_event(MonitoringEventType.HOST_BECAME_AVAILABLE, target, timestamp),
        ]
        alerts = generate_alerts(events)

        assert len(alerts) == 4
        assert alerts[0].alert_type == AlertType.NEW_OPEN_PORT
        assert alerts[0].severity == Severity.HIGH
        assert alerts[1].alert_type == AlertType.PORT_CLOSED
        assert alerts[1].severity == Severity.LOW
        assert alerts[2].alert_type == AlertType.HOST_DOWN
        assert alerts[2].severity == Severity.MEDIUM
        assert alerts[3].alert_type == AlertType.HOST_RECOVERED
        assert alerts[3].severity == Severity.INFO


# -----------------------------------------------------------------------
# Deterministic ordering
# -----------------------------------------------------------------------
class TestDeterministicOrdering:
    def test_output_follows_input_order(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        """Alerts are produced in the same order as the input events."""
        events = [
            _make_event(MonitoringEventType.HOST_BECAME_AVAILABLE, target, timestamp),
            _make_event(MonitoringEventType.PORT_OPENED, target, timestamp, port=443),
            _make_event(MonitoringEventType.PORT_CLOSED, target, timestamp, port=22),
        ]
        alerts = generate_alerts(events)

        assert len(alerts) == 3
        assert alerts[0].alert_type == AlertType.HOST_RECOVERED
        assert alerts[1].alert_type == AlertType.NEW_OPEN_PORT
        assert alerts[2].alert_type == AlertType.PORT_CLOSED

    def test_reversed_input_produces_reversed_output(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        events_a = [
            _make_event(MonitoringEventType.PORT_OPENED, target, timestamp, port=80),
            _make_event(MonitoringEventType.PORT_CLOSED, target, timestamp, port=22),
        ]
        events_b = list(reversed(events_a))

        alerts_a = generate_alerts(events_a)
        alerts_b = generate_alerts(events_b)

        assert alerts_a[0].alert_type == AlertType.NEW_OPEN_PORT
        assert alerts_a[1].alert_type == AlertType.PORT_CLOSED
        assert alerts_b[0].alert_type == AlertType.PORT_CLOSED
        assert alerts_b[1].alert_type == AlertType.NEW_OPEN_PORT


# -----------------------------------------------------------------------
# Timestamp preservation
# -----------------------------------------------------------------------
class TestTimestampPreservation:
    def test_alert_uses_event_timestamp(self, target: NetworkTarget) -> None:
        """The alert timestamp must come from the event, not datetime.now()."""
        specific_time = datetime(2024, 3, 15, 8, 30, 0, tzinfo=UTC)
        event = _make_event(
            MonitoringEventType.PORT_OPENED, target, specific_time, port=443
        )
        alert = evaluate_event(event)
        assert alert is not None
        assert alert.timestamp == specific_time

    def test_different_events_preserve_their_timestamps(
        self, target: NetworkTarget
    ) -> None:
        t1 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2025, 1, 1, 10, 5, 0, tzinfo=UTC)

        events = [
            _make_event(MonitoringEventType.PORT_OPENED, target, t1, port=80),
            _make_event(MonitoringEventType.PORT_CLOSED, target, t2, port=22),
        ]
        alerts = generate_alerts(events)

        assert alerts[0].timestamp == t1
        assert alerts[1].timestamp == t2


# -----------------------------------------------------------------------
# Target preservation
# -----------------------------------------------------------------------
class TestTargetPreservation:
    def test_alert_preserves_target(self, timestamp: datetime) -> None:
        target_a = NetworkTarget.parse("10.0.0.1")
        target_b = NetworkTarget.parse("10.0.0.2")

        event_a = _make_event(
            MonitoringEventType.PORT_OPENED, target_a, timestamp, port=80
        )
        event_b = _make_event(
            MonitoringEventType.HOST_BECAME_UNAVAILABLE, target_b, timestamp
        )

        alert_a = evaluate_event(event_a)
        alert_b = evaluate_event(event_b)

        assert alert_a is not None
        assert alert_a.target == target_a
        assert alert_b is not None
        assert alert_b.target == target_b


# -----------------------------------------------------------------------
# Port preservation
# -----------------------------------------------------------------------
class TestPortPreservation:
    def test_port_events_preserve_port(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        event = _make_event(
            MonitoringEventType.PORT_OPENED, target, timestamp, port=5432
        )
        alert = evaluate_event(event)
        assert alert is not None
        assert alert.port == 5432

    def test_host_events_have_none_port(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        for event_type in (
            MonitoringEventType.HOST_BECAME_UNAVAILABLE,
            MonitoringEventType.HOST_BECAME_AVAILABLE,
        ):
            event = _make_event(event_type, target, timestamp)
            alert = evaluate_event(event)
            assert alert is not None
            assert alert.port is None


# -----------------------------------------------------------------------
# SecurityAlert is frozen
# -----------------------------------------------------------------------
class TestAlertImmutability:
    def test_security_alert_is_frozen(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        event = _make_event(MonitoringEventType.PORT_OPENED, target, timestamp, port=80)
        alert = evaluate_event(event)
        assert alert is not None
        with pytest.raises(AttributeError):
            alert.severity = Severity.LOW  # type: ignore[misc]


# -----------------------------------------------------------------------
# Enum values
# -----------------------------------------------------------------------
class TestEnumValues:
    def test_alert_type_values(self) -> None:
        assert AlertType.NEW_OPEN_PORT == "new_open_port"
        assert AlertType.PORT_CLOSED == "port_closed"
        assert AlertType.HOST_DOWN == "host_down"
        assert AlertType.HOST_RECOVERED == "host_recovered"

    def test_severity_values(self) -> None:
        assert Severity.INFO == "info"
        assert Severity.LOW == "low"
        assert Severity.MEDIUM == "medium"
        assert Severity.HIGH == "high"
        assert Severity.CRITICAL == "critical"

    def test_severity_critical_exists_but_unused(self) -> None:
        """CRITICAL is defined in the enum but no current rule produces it."""
        assert hasattr(Severity, "CRITICAL")
        # Confirm no current rule generates CRITICAL
        all_event_types = list(MonitoringEventType)
        target = NetworkTarget.parse("127.0.0.1")
        ts = datetime(2025, 1, 1, tzinfo=UTC)
        for et in all_event_types:
            event = _make_event(et, target, ts, port=80 if "PORT" in et.name else None)
            alert = evaluate_event(event)
            if alert is not None:
                assert alert.severity != Severity.CRITICAL


# -----------------------------------------------------------------------
# AlertPolicy and configurable severities
# -----------------------------------------------------------------------
class TestAlertPolicyDefaults:
    def test_default_policy_severities(self) -> None:
        policy = DEFAULT_ALERT_POLICY
        assert policy.new_open_port_severity == Severity.HIGH
        assert policy.port_closed_severity == Severity.LOW
        assert policy.host_down_severity == Severity.MEDIUM
        assert policy.host_recovered_severity == Severity.INFO

    def test_default_policy_instance_equality(self) -> None:
        assert AlertPolicy() == DEFAULT_ALERT_POLICY

    def test_policy_is_frozen(self) -> None:
        policy = AlertPolicy()
        with pytest.raises(AttributeError):
            policy.new_open_port_severity = Severity.CRITICAL  # type: ignore[misc]


class TestCustomAlertPolicy:
    def test_custom_new_open_port_severity(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        policy = AlertPolicy(new_open_port_severity=Severity.CRITICAL)
        event = _make_event(
            MonitoringEventType.PORT_OPENED, target, timestamp, port=443
        )
        alert = evaluate_event(event, policy=policy)

        assert alert is not None
        assert alert.alert_type == AlertType.NEW_OPEN_PORT
        assert alert.severity == Severity.CRITICAL
        # Preserves other attributes
        assert alert.port == 443
        assert alert.target == target
        assert alert.timestamp == timestamp
        assert alert.source_event_type == "port_opened"

    def test_custom_port_closed_severity(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        policy = AlertPolicy(port_closed_severity=Severity.HIGH)
        event = _make_event(MonitoringEventType.PORT_CLOSED, target, timestamp, port=22)
        alert = evaluate_event(event, policy=policy)

        assert alert is not None
        assert alert.alert_type == AlertType.PORT_CLOSED
        assert alert.severity == Severity.HIGH

    def test_custom_host_down_severity(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        policy = AlertPolicy(host_down_severity=Severity.CRITICAL)
        event = _make_event(
            MonitoringEventType.HOST_BECAME_UNAVAILABLE, target, timestamp
        )
        alert = evaluate_event(event, policy=policy)

        assert alert is not None
        assert alert.alert_type == AlertType.HOST_DOWN
        assert alert.severity == Severity.CRITICAL

    def test_custom_host_recovered_severity(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        policy = AlertPolicy(host_recovered_severity=Severity.LOW)
        event = _make_event(
            MonitoringEventType.HOST_BECAME_AVAILABLE, target, timestamp
        )
        alert = evaluate_event(event, policy=policy)

        assert alert is not None
        assert alert.alert_type == AlertType.HOST_RECOVERED
        assert alert.severity == Severity.LOW

    def test_generate_alerts_with_custom_policy(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        policy = AlertPolicy(
            new_open_port_severity=Severity.CRITICAL,
            port_closed_severity=Severity.INFO,
            host_down_severity=Severity.HIGH,
            host_recovered_severity=Severity.MEDIUM,
        )
        events = [
            _make_event(MonitoringEventType.PORT_OPENED, target, timestamp, port=80),
            _make_event(MonitoringEventType.PORT_CLOSED, target, timestamp, port=22),
            _make_event(MonitoringEventType.HOST_BECAME_UNAVAILABLE, target, timestamp),
            _make_event(MonitoringEventType.HOST_BECAME_AVAILABLE, target, timestamp),
        ]
        alerts = generate_alerts(events, policy=policy)

        assert len(alerts) == 4
        assert alerts[0].severity == Severity.CRITICAL
        assert alerts[1].severity == Severity.INFO
        assert alerts[2].severity == Severity.HIGH
        assert alerts[3].severity == Severity.MEDIUM

    def test_generate_alerts_empty_with_custom_policy(self) -> None:
        policy = AlertPolicy(new_open_port_severity=Severity.CRITICAL)
        assert generate_alerts([], policy=policy) == []


class TestSeverityParsing:
    def test_parse_severity_valid_strings(self) -> None:
        assert _parse_severity("INFO", "SETTING") == Severity.INFO
        assert _parse_severity("LOW", "SETTING") == Severity.LOW
        assert _parse_severity("MEDIUM", "SETTING") == Severity.MEDIUM
        assert _parse_severity("HIGH", "SETTING") == Severity.HIGH
        assert _parse_severity("CRITICAL", "SETTING") == Severity.CRITICAL

    def test_parse_severity_case_insensitive_and_whitespace(self) -> None:
        assert _parse_severity("info", "SETTING") == Severity.INFO
        assert _parse_severity("Low", "SETTING") == Severity.LOW
        assert _parse_severity("  medium  ", "SETTING") == Severity.MEDIUM
        assert _parse_severity("hIgH", "SETTING") == Severity.HIGH
        assert _parse_severity("critical", "SETTING") == Severity.CRITICAL

    def test_parse_severity_enum_passthrough(self) -> None:
        assert _parse_severity(Severity.HIGH, "SETTING") == Severity.HIGH
        assert _parse_severity(Severity.CRITICAL, "SETTING") == Severity.CRITICAL

    def test_parse_severity_invalid_raises_value_error(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            _parse_severity("BANANA", "ALERT_SEVERITY_NEW_OPEN_PORT")
        msg = str(exc_info.value)
        expected = "Invalid alert severity for ALERT_SEVERITY_NEW_OPEN_PORT: 'BANANA'"
        assert expected in msg
        assert "Must be one of: INFO, LOW, MEDIUM, HIGH, CRITICAL" in msg

    def test_parse_severity_other_invalids(self) -> None:
        for invalid in ("EXTREME", "SEVERE", "", "123", "none"):
            with pytest.raises(ValueError):
                _parse_severity(invalid, "TEST_SETTING")


class TestSettingsAlertPolicy:
    def test_settings_default_policy(self) -> None:
        s = Settings()
        policy = s.get_alert_policy()
        assert policy == DEFAULT_ALERT_POLICY

    def test_settings_custom_severities(self) -> None:
        s = Settings(
            ALERT_SEVERITY_NEW_OPEN_PORT="critical",
            ALERT_SEVERITY_PORT_CLOSED="medium",
            ALERT_SEVERITY_HOST_DOWN="high",
            ALERT_SEVERITY_HOST_RECOVERED="low",
        )
        policy = s.get_alert_policy()
        assert policy.new_open_port_severity == Severity.CRITICAL
        assert policy.port_closed_severity == Severity.MEDIUM
        assert policy.host_down_severity == Severity.HIGH
        assert policy.host_recovered_severity == Severity.LOW

    def test_settings_invalid_severity_raises(self) -> None:
        s = Settings(ALERT_SEVERITY_NEW_OPEN_PORT="INVALID_SEV")
        with pytest.raises(ValueError) as exc_info:
            s.get_alert_policy()
        msg = str(exc_info.value)
        expected = (
            "Invalid alert severity for ALERT_SEVERITY_NEW_OPEN_PORT: 'INVALID_SEV'"
        )
        assert expected in msg

    def test_settings_expected_ports_default_is_none(self) -> None:
        s = Settings()
        assert s.get_alert_policy().expected_tcp_ports is None

    def test_settings_expected_ports_empty_string_is_none(self) -> None:
        s = Settings(EXPECTED_TCP_PORTS="")
        assert s.get_alert_policy().expected_tcp_ports is None

    def test_settings_expected_ports_configured(self) -> None:
        s = Settings(EXPECTED_TCP_PORTS="22, 80, 443")
        policy = s.get_alert_policy()
        assert policy.expected_tcp_ports == frozenset({22, 80, 443})

    def test_settings_expected_ports_invalid_raises(self) -> None:
        s = Settings(EXPECTED_TCP_PORTS="22,abc")
        with pytest.raises(ValueError) as exc_info:
            s.get_alert_policy()
        assert "Invalid expected TCP port: 'abc'" in str(exc_info.value)

    def test_settings_custom_expected_port_severities(self) -> None:
        s = Settings(
            ALERT_SEVERITY_EXPECTED_OPEN_PORT="low",
            ALERT_SEVERITY_UNEXPECTED_OPEN_PORT="critical",
        )
        policy = s.get_alert_policy()
        assert policy.expected_open_port_severity == Severity.LOW
        assert policy.unexpected_open_port_severity == Severity.CRITICAL


# -----------------------------------------------------------------------
# Expected TCP Ports Policy (v0.4.0)
# -----------------------------------------------------------------------
class TestExpectedPortsAlertPolicy:
    def test_expected_port_opened_generates_expected_open_port(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        policy = AlertPolicy(expected_tcp_ports=frozenset({22, 80, 443}))
        event = _make_event(
            MonitoringEventType.PORT_OPENED, target, timestamp, port=443
        )
        alert = evaluate_event(event, policy=policy)

        assert alert is not None
        assert alert.alert_type == AlertType.EXPECTED_OPEN_PORT
        assert alert.severity == Severity.INFO
        assert alert.port == 443
        assert alert.target == target
        assert alert.timestamp == timestamp
        assert alert.source_event_type == "port_opened"
        assert alert.message == f"Expected TCP port 443 became open on {target.value}."

    def test_unexpected_port_opened_generates_unexpected_open_port(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        policy = AlertPolicy(expected_tcp_ports=frozenset({22, 80, 443}))
        event = _make_event(
            MonitoringEventType.PORT_OPENED, target, timestamp, port=8080
        )
        alert = evaluate_event(event, policy=policy)

        assert alert is not None
        assert alert.alert_type == AlertType.UNEXPECTED_OPEN_PORT
        assert alert.severity == Severity.HIGH
        assert alert.port == 8080
        assert alert.target == target
        assert alert.timestamp == timestamp
        assert alert.source_event_type == "port_opened"
        assert alert.message == (
            f"Unexpected TCP port 8080 became open on {target.value}."
        )

    def test_custom_severities_for_expected_and_unexpected(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        policy = AlertPolicy(
            expected_tcp_ports=frozenset({443}),
            expected_open_port_severity=Severity.LOW,
            unexpected_open_port_severity=Severity.CRITICAL,
        )
        exp_event = _make_event(
            MonitoringEventType.PORT_OPENED, target, timestamp, port=443
        )
        unexp_event = _make_event(
            MonitoringEventType.PORT_OPENED, target, timestamp, port=8080
        )

        exp_alert = evaluate_event(exp_event, policy=policy)
        unexp_alert = evaluate_event(unexp_event, policy=policy)

        assert exp_alert is not None
        assert exp_alert.alert_type == AlertType.EXPECTED_OPEN_PORT
        assert exp_alert.severity == Severity.LOW

        assert unexp_alert is not None
        assert unexp_alert.alert_type == AlertType.UNEXPECTED_OPEN_PORT
        assert unexp_alert.severity == Severity.CRITICAL

    def test_disabled_policy_preserves_new_open_port(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        policy = AlertPolicy(expected_tcp_ports=None)
        event = _make_event(
            MonitoringEventType.PORT_OPENED, target, timestamp, port=443
        )
        alert = evaluate_event(event, policy=policy)

        assert alert is not None
        assert alert.alert_type == AlertType.NEW_OPEN_PORT
        assert alert.severity == Severity.HIGH

    def test_other_events_unaffected_by_expected_ports(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        policy = AlertPolicy(expected_tcp_ports=frozenset({22, 80, 443}))

        # Port closed for an expected port
        c_exp = _make_event(
            MonitoringEventType.PORT_CLOSED, target, timestamp, port=443
        )
        # Port closed for an unexpected port
        c_unexp = _make_event(
            MonitoringEventType.PORT_CLOSED, target, timestamp, port=8080
        )
        h_down = _make_event(
            MonitoringEventType.HOST_BECAME_UNAVAILABLE, target, timestamp
        )
        h_rec = _make_event(
            MonitoringEventType.HOST_BECAME_AVAILABLE, target, timestamp
        )

        a_c_exp = evaluate_event(c_exp, policy=policy)
        a_c_unexp = evaluate_event(c_unexp, policy=policy)
        a_h_down = evaluate_event(h_down, policy=policy)
        a_h_rec = evaluate_event(h_rec, policy=policy)

        assert a_c_exp is not None and a_c_exp.alert_type == AlertType.PORT_CLOSED
        assert a_c_unexp is not None and a_c_unexp.alert_type == AlertType.PORT_CLOSED
        assert a_h_down is not None and a_h_down.alert_type == AlertType.HOST_DOWN
        assert a_h_rec is not None and a_h_rec.alert_type == AlertType.HOST_RECOVERED

    def test_multiple_ports_deterministic_order(
        self, target: NetworkTarget, timestamp: datetime
    ) -> None:
        policy = AlertPolicy(expected_tcp_ports=frozenset({22, 80, 443}))
        events = [
            _make_event(MonitoringEventType.PORT_OPENED, target, timestamp, port=22),
            _make_event(MonitoringEventType.PORT_OPENED, target, timestamp, port=8080),
            _make_event(MonitoringEventType.PORT_OPENED, target, timestamp, port=443),
            _make_event(MonitoringEventType.PORT_OPENED, target, timestamp, port=9000),
        ]
        alerts = generate_alerts(events, policy=policy)

        assert len(alerts) == 4
        assert alerts[0].alert_type == AlertType.EXPECTED_OPEN_PORT
        assert alerts[0].port == 22
        assert alerts[0].severity == Severity.INFO

        assert alerts[1].alert_type == AlertType.UNEXPECTED_OPEN_PORT
        assert alerts[1].port == 8080
        assert alerts[1].severity == Severity.HIGH

        assert alerts[2].alert_type == AlertType.EXPECTED_OPEN_PORT
        assert alerts[2].port == 443
        assert alerts[2].severity == Severity.INFO

        assert alerts[3].alert_type == AlertType.UNEXPECTED_OPEN_PORT
        assert alerts[3].port == 9000
        assert alerts[3].severity == Severity.HIGH


class TestExpectedPortsParsing:
    def test_parse_valid(self) -> None:
        assert _parse_expected_tcp_ports("22,80,443") == frozenset({22, 80, 443})

    def test_parse_whitespace_and_deduplication(self) -> None:
        assert _parse_expected_tcp_ports(" 443, 22, 443 ") == frozenset({22, 443})

    def test_parse_empty_and_none(self) -> None:
        assert _parse_expected_tcp_ports("") is None
        assert _parse_expected_tcp_ports("   ") is None
        assert _parse_expected_tcp_ports(None) is None

    def test_parse_invalid_values(self) -> None:
        invalids = ["0", "65536", "-1", "abc", "80,http", "22,,443", ",80", "80,"]
        for inv in invalids:
            with pytest.raises(ValueError):
                _parse_expected_tcp_ports(inv)
