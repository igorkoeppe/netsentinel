"""Unit tests for NotificationPolicy and severity threshold filtering."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.config import Settings
from app.detection.alerts import AlertStatus, AlertType, SecurityAlert, Severity
from app.monitoring.target import NetworkTarget
from app.notifications.models import Notification, NotificationChannel
from app.notifications.policy import (
    DEFAULT_NOTIFICATION_POLICY,
    NotificationPolicy,
    notification_for_alert,
    should_notify,
)


def _make_alert(
    severity: Severity,
    *,
    alert_type: AlertType = AlertType.NEW_OPEN_PORT,
    port: int | None = 443,
    status: AlertStatus = AlertStatus.OPEN,
) -> SecurityAlert:
    """Helper to create a SecurityAlert with specific parameters for testing."""
    return SecurityAlert(
        alert_type=alert_type,
        severity=severity,
        target=NetworkTarget.parse("192.168.1.1"),
        timestamp=datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC),
        message=f"Test alert with severity {severity.value}",
        port=port,
        source_event_type="port_opened",
        status=status,
    )


# ---------------------------------------------------------------------------
# Core Policy Tests
# ---------------------------------------------------------------------------


class TestNotificationPolicyDefaults:
    def test_default_policy_minimum_severity_is_high(self) -> None:
        policy = NotificationPolicy()
        assert policy.minimum_severity == Severity.HIGH
        assert DEFAULT_NOTIFICATION_POLICY.minimum_severity == Severity.HIGH

    def test_default_high_severity_threshold(self) -> None:
        policy = NotificationPolicy()

        assert policy.should_notify(_make_alert(Severity.INFO)) is False
        assert policy.should_notify(_make_alert(Severity.LOW)) is False
        assert policy.should_notify(_make_alert(Severity.MEDIUM)) is False
        assert policy.should_notify(_make_alert(Severity.HIGH)) is True
        assert policy.should_notify(_make_alert(Severity.CRITICAL)) is True

    def test_functional_should_notify_with_default(self) -> None:
        assert should_notify(_make_alert(Severity.INFO)) is False
        assert should_notify(_make_alert(Severity.LOW)) is False
        assert should_notify(_make_alert(Severity.MEDIUM)) is False
        assert should_notify(_make_alert(Severity.HIGH)) is True
        assert should_notify(_make_alert(Severity.CRITICAL)) is True


class TestNotificationPolicyThresholds:
    def test_medium_threshold(self) -> None:
        policy = NotificationPolicy(minimum_severity=Severity.MEDIUM)

        assert policy.should_notify(_make_alert(Severity.INFO)) is False
        assert policy.should_notify(_make_alert(Severity.LOW)) is False
        assert policy.should_notify(_make_alert(Severity.MEDIUM)) is True
        assert policy.should_notify(_make_alert(Severity.HIGH)) is True
        assert policy.should_notify(_make_alert(Severity.CRITICAL)) is True

    def test_info_threshold_notifies_all(self) -> None:
        policy = NotificationPolicy(minimum_severity=Severity.INFO)

        for severity in Severity:
            assert policy.should_notify(_make_alert(severity)) is True

    def test_critical_threshold_only_notifies_critical(self) -> None:
        policy = NotificationPolicy(minimum_severity=Severity.CRITICAL)

        assert policy.should_notify(_make_alert(Severity.INFO)) is False
        assert policy.should_notify(_make_alert(Severity.LOW)) is False
        assert policy.should_notify(_make_alert(Severity.MEDIUM)) is False
        assert policy.should_notify(_make_alert(Severity.HIGH)) is False
        assert policy.should_notify(_make_alert(Severity.CRITICAL)) is True

    def test_low_threshold(self) -> None:
        policy = NotificationPolicy(minimum_severity=Severity.LOW)

        assert policy.should_notify(_make_alert(Severity.INFO)) is False
        assert policy.should_notify(_make_alert(Severity.LOW)) is True
        assert policy.should_notify(_make_alert(Severity.MEDIUM)) is True
        assert policy.should_notify(_make_alert(Severity.HIGH)) is True
        assert policy.should_notify(_make_alert(Severity.CRITICAL)) is True

    def test_boundary_equality_always_notifies(self) -> None:
        for severity in Severity:
            policy = NotificationPolicy(minimum_severity=severity)
            assert policy.should_notify(_make_alert(severity)) is True


# ---------------------------------------------------------------------------
# Orthogonality & Isolation Tests
# ---------------------------------------------------------------------------


class TestNotificationPolicyOrthogonality:
    def test_alert_type_does_not_influence_decision(self) -> None:
        policy = NotificationPolicy(minimum_severity=Severity.HIGH)

        alert1 = _make_alert(Severity.HIGH, alert_type=AlertType.UNEXPECTED_OPEN_PORT)
        alert2 = _make_alert(Severity.HIGH, alert_type=AlertType.HOST_DOWN)
        alert3 = _make_alert(Severity.HIGH, alert_type=AlertType.PORT_CLOSED)

        assert policy.should_notify(alert1) is True
        assert policy.should_notify(alert2) is True
        assert policy.should_notify(alert3) is True

        low1 = _make_alert(Severity.LOW, alert_type=AlertType.UNEXPECTED_OPEN_PORT)
        low2 = _make_alert(Severity.LOW, alert_type=AlertType.HOST_DOWN)
        assert policy.should_notify(low1) is False
        assert policy.should_notify(low2) is False

    def test_port_presence_does_not_influence_decision(self) -> None:
        policy = NotificationPolicy(minimum_severity=Severity.HIGH)

        alert_with_port = _make_alert(Severity.HIGH, port=443)
        alert_without_port = _make_alert(Severity.HIGH, port=None)

        assert policy.should_notify(alert_with_port) is True
        assert policy.should_notify(alert_without_port) is True

    def test_lifecycle_status_does_not_influence_decision(self) -> None:
        policy = NotificationPolicy(minimum_severity=Severity.HIGH)

        open_alert = _make_alert(Severity.HIGH, status=AlertStatus.OPEN)
        ack_alert = _make_alert(Severity.HIGH, status=AlertStatus.ACKNOWLEDGED)
        res_alert = _make_alert(Severity.HIGH, status=AlertStatus.RESOLVED)

        assert policy.should_notify(open_alert) is True
        assert policy.should_notify(ack_alert) is True
        assert policy.should_notify(res_alert) is True

    def test_security_alert_is_not_mutated(self) -> None:
        policy = NotificationPolicy(minimum_severity=Severity.HIGH)
        alert = _make_alert(Severity.HIGH)

        original_repr = repr(alert)
        _ = policy.should_notify(alert)
        assert repr(alert) == original_repr


# ---------------------------------------------------------------------------
# High-Level Helper Tests
# ---------------------------------------------------------------------------


class TestNotificationForAlertHelper:
    def test_returns_notification_when_threshold_met(self) -> None:
        policy = NotificationPolicy(minimum_severity=Severity.HIGH)
        alert = _make_alert(Severity.HIGH)

        notif = notification_for_alert(
            alert, policy, channel=NotificationChannel.CONSOLE
        )

        assert isinstance(notif, Notification)
        assert notif.severity == "high"
        assert notif.target_address == "192.168.1.1"
        assert notif.channel == NotificationChannel.CONSOLE

    def test_returns_none_when_threshold_not_met(self) -> None:
        policy = NotificationPolicy(minimum_severity=Severity.HIGH)
        alert = _make_alert(Severity.MEDIUM)

        notif = notification_for_alert(alert, policy, channel=NotificationChannel.LOG)
        assert notif is None


# ---------------------------------------------------------------------------
# Configuration Parsing Tests
# ---------------------------------------------------------------------------


class TestNotificationPolicyConfiguration:
    def test_default_config_produces_high_policy(self) -> None:
        cfg = Settings()
        policy = cfg.get_notification_policy()
        assert policy.minimum_severity == Severity.HIGH

    def test_valid_config_severity(self) -> None:
        cfg = Settings(NOTIFICATION_MIN_SEVERITY="MEDIUM")
        policy = cfg.get_notification_policy()
        assert policy.minimum_severity == Severity.MEDIUM

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("info", Severity.INFO),
            ("Info", Severity.INFO),
            ("INFO", Severity.INFO),
            ("low", Severity.LOW),
            ("Low", Severity.LOW),
            ("LOW", Severity.LOW),
            ("medium", Severity.MEDIUM),
            ("Medium", Severity.MEDIUM),
            ("MEDIUM", Severity.MEDIUM),
            ("high", Severity.HIGH),
            ("High", Severity.HIGH),
            ("HIGH", Severity.HIGH),
            ("critical", Severity.CRITICAL),
            ("Critical", Severity.CRITICAL),
            ("CRITICAL", Severity.CRITICAL),
            ("  high  ", Severity.HIGH),
        ],
    )
    def test_config_case_insensitive_parsing(
        self, value: str, expected: Severity
    ) -> None:
        cfg = Settings(NOTIFICATION_MIN_SEVERITY=value)
        policy = cfg.get_notification_policy()
        assert policy.minimum_severity == expected

    @pytest.mark.parametrize(
        "invalid_value",
        ["EXTREME", "URGENT", "SEVERE", "None", "123", "", "   "],
    )
    def test_invalid_config_raises_clear_error_without_fallback(
        self, invalid_value: str
    ) -> None:
        cfg = Settings(NOTIFICATION_MIN_SEVERITY=invalid_value)
        with pytest.raises(ValueError) as exc_info:
            cfg.get_notification_policy()

        err_msg = str(exc_info.value)
        assert "Invalid alert severity for NOTIFICATION_MIN_SEVERITY" in err_msg
        assert invalid_value in err_msg or "''" in err_msg
