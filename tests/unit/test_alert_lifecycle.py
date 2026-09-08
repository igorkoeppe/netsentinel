"""Unit tests for SecurityAlert lifecycle and triage state machine."""

from datetime import UTC, datetime, timedelta

import pytest

from app.detection.alerts import (
    AlertLifecycle,
    AlertStatus,
    AlertType,
    InvalidAlertStateTransitionError,
    SecurityAlert,
    Severity,
)
from app.monitoring.target import NetworkTarget

_BASE_TIME = datetime(2026, 9, 4, 12, 0, 0, tzinfo=UTC)


def _make_alert(
    *,
    alert_type: AlertType = AlertType.NEW_OPEN_PORT,
    severity: Severity = Severity.HIGH,
    timestamp: datetime = _BASE_TIME,
    status: AlertStatus = AlertStatus.OPEN,
    acknowledged_at: datetime | None = None,
    resolved_at: datetime | None = None,
) -> SecurityAlert:
    return SecurityAlert(
        alert_type=alert_type,
        severity=severity,
        target=NetworkTarget.parse("127.0.0.1"),
        timestamp=timestamp,
        message="Test alert message",
        port=80,
        source_event_type="port_opened",
        status=status,
        acknowledged_at=acknowledged_at,
        resolved_at=resolved_at,
    )


class TestAlertStatusEnum:
    def test_enum_members_and_values(self) -> None:
        assert AlertStatus.OPEN == "OPEN"
        assert AlertStatus.ACKNOWLEDGED == "ACKNOWLEDGED"
        assert AlertStatus.RESOLVED == "RESOLVED"
        assert len(AlertStatus) == 3


class TestAlertInitialState:
    def test_default_status_is_open(self) -> None:
        alert = _make_alert()
        assert alert.status == AlertStatus.OPEN
        assert alert.acknowledged_at is None
        assert alert.resolved_at is None
        assert alert.is_open is True
        assert alert.is_acknowledged is False
        assert alert.is_resolved is False


class TestValidTransitions:
    def test_open_to_acknowledged(self) -> None:
        alert = _make_alert()
        ack_time = _BASE_TIME + timedelta(minutes=5)
        ack_alert = alert.acknowledge(at=ack_time)

        assert ack_alert.status == AlertStatus.ACKNOWLEDGED
        assert ack_alert.acknowledged_at == ack_time
        assert ack_alert.resolved_at is None
        assert ack_alert.is_open is False
        assert ack_alert.is_acknowledged is True
        assert ack_alert.is_resolved is False

    def test_open_to_resolved_direct(self) -> None:
        alert = _make_alert()
        res_time = _BASE_TIME + timedelta(minutes=10)
        res_alert = alert.resolve(at=res_time)

        assert res_alert.status == AlertStatus.RESOLVED
        assert res_alert.acknowledged_at is None
        assert res_alert.resolved_at == res_time
        assert res_alert.is_open is False
        assert res_alert.is_acknowledged is False
        assert res_alert.is_resolved is True

    def test_acknowledged_to_resolved(self) -> None:
        alert = _make_alert()
        ack_time = _BASE_TIME + timedelta(minutes=5)
        ack_alert = alert.acknowledge(at=ack_time)

        res_time = _BASE_TIME + timedelta(minutes=15)
        res_alert = ack_alert.resolve(at=res_time)

        assert res_alert.status == AlertStatus.RESOLVED
        assert res_alert.acknowledged_at == ack_time
        assert res_alert.resolved_at == res_time
        assert res_alert.is_open is False
        assert res_alert.is_acknowledged is False
        assert res_alert.is_resolved is True

    def test_acknowledged_to_open_unacknowledge(self) -> None:
        alert = _make_alert()
        ack_alert = alert.acknowledge(at=_BASE_TIME + timedelta(minutes=5))
        unack_alert = ack_alert.unacknowledge()

        assert unack_alert.status == AlertStatus.OPEN
        assert unack_alert.acknowledged_at is None
        assert unack_alert.resolved_at is None
        assert unack_alert.is_open is True
        assert unack_alert.is_acknowledged is False
        assert unack_alert.is_resolved is False

    def test_resolved_to_open_reopen(self) -> None:
        alert = _make_alert()
        ack_alert = alert.acknowledge(at=_BASE_TIME + timedelta(minutes=5))
        res_alert = ack_alert.resolve(at=_BASE_TIME + timedelta(minutes=10))

        reopened = res_alert.reopen()

        assert reopened.status == AlertStatus.OPEN
        assert reopened.acknowledged_at is None
        assert reopened.resolved_at is None
        assert reopened.is_open is True
        assert reopened.is_resolved is False

    def test_transition_to_default_timestamp_is_utc_now(self) -> None:
        alert = _make_alert()
        ack_alert = alert.acknowledge()

        assert ack_alert.status == AlertStatus.ACKNOWLEDGED
        assert ack_alert.acknowledged_at is not None
        assert ack_alert.acknowledged_at.tzinfo is not None


class TestInvalidTransitions:
    def test_resolved_to_acknowledged_is_rejected(self) -> None:
        alert = _make_alert().resolve(at=_BASE_TIME + timedelta(minutes=10))
        with pytest.raises(InvalidAlertStateTransitionError) as exc_info:
            alert.transition_to(AlertStatus.ACKNOWLEDGED)

        assert exc_info.value.current_status == AlertStatus.RESOLVED
        assert exc_info.value.target_status == AlertStatus.ACKNOWLEDGED
        assert "Cannot transition alert from RESOLVED to ACKNOWLEDGED" in str(
            exc_info.value
        )

    def test_self_transitions_are_rejected(self) -> None:
        open_alert = _make_alert()
        with pytest.raises(InvalidAlertStateTransitionError) as exc_info:
            open_alert.transition_to(AlertStatus.OPEN)
        assert exc_info.value.current_status == AlertStatus.OPEN
        assert exc_info.value.target_status == AlertStatus.OPEN

        ack_alert = open_alert.acknowledge(at=_BASE_TIME + timedelta(minutes=1))
        with pytest.raises(InvalidAlertStateTransitionError) as exc_info:
            ack_alert.acknowledge()
        assert exc_info.value.current_status == AlertStatus.ACKNOWLEDGED
        assert exc_info.value.target_status == AlertStatus.ACKNOWLEDGED

        res_alert = ack_alert.resolve(at=_BASE_TIME + timedelta(minutes=2))
        with pytest.raises(InvalidAlertStateTransitionError) as exc_info:
            res_alert.resolve()
        assert exc_info.value.current_status == AlertStatus.RESOLVED
        assert exc_info.value.target_status == AlertStatus.RESOLVED


class TestImmutability:
    def test_transition_methods_return_new_instance(self) -> None:
        original = _make_alert()
        ack = original.acknowledge(at=_BASE_TIME + timedelta(minutes=5))

        # Original is untouched
        assert original.status == AlertStatus.OPEN
        assert original.acknowledged_at is None
        assert original is not ack

        # ack has new state
        assert ack.status == AlertStatus.ACKNOWLEDGED
        assert ack.acknowledged_at is not None

    def test_frozen_dataclass_prevents_direct_mutation(self) -> None:
        alert = _make_alert()
        with pytest.raises(AttributeError):
            alert.status = AlertStatus.ACKNOWLEDGED  # type: ignore[misc]

        with pytest.raises(AttributeError):
            alert.acknowledged_at = _BASE_TIME  # type: ignore[misc]


class TestTimestampValidations:
    def test_acknowledged_at_cannot_be_before_timestamp(self) -> None:
        earlier = _BASE_TIME - timedelta(seconds=1)
        alert = _make_alert(timestamp=_BASE_TIME)
        with pytest.raises(ValueError, match="cannot be earlier than alert timestamp"):
            alert.acknowledge(at=earlier)

    def test_resolved_at_cannot_be_before_timestamp(self) -> None:
        earlier = _BASE_TIME - timedelta(seconds=1)
        alert = _make_alert(timestamp=_BASE_TIME)
        with pytest.raises(ValueError, match="cannot be earlier than alert timestamp"):
            alert.resolve(at=earlier)

    def test_resolved_at_cannot_be_before_acknowledged_at(self) -> None:
        alert = _make_alert(timestamp=_BASE_TIME).acknowledge(
            at=_BASE_TIME + timedelta(minutes=10)
        )
        invalid_res_time = _BASE_TIME + timedelta(minutes=5)
        with pytest.raises(ValueError, match="cannot be earlier than acknowledged_at"):
            alert.resolve(at=invalid_res_time)

    def test_naive_vs_aware_datetimes_comparison_handled_cleanly(self) -> None:
        # Naive timestamp should not raise TypeError
        naive_now = datetime(2026, 9, 4, 12, 0, 0)
        alert = _make_alert(timestamp=naive_now)
        ack = alert.acknowledge(at=naive_now + timedelta(minutes=1))
        assert ack.status == AlertStatus.ACKNOWLEDGED


class TestAlertLifecycleValueObject:
    def test_default_lifecycle(self) -> None:
        lifecycle = AlertLifecycle()
        assert lifecycle.status == AlertStatus.OPEN
        assert lifecycle.acknowledged_at is None
        assert lifecycle.resolved_at is None
        assert lifecycle.is_open is True
        assert lifecycle.is_acknowledged is False
        assert lifecycle.is_resolved is False

    def test_lifecycle_transitions(self) -> None:
        now = datetime.now(UTC)
        lc = AlertLifecycle()

        # OPEN -> ACKNOWLEDGED
        ack = lc.acknowledge(at=now)
        assert ack.status == AlertStatus.ACKNOWLEDGED
        assert ack.acknowledged_at == now
        assert ack.is_acknowledged is True

        # ACKNOWLEDGED -> RESOLVED
        res_time = now + timedelta(minutes=5)
        res = ack.resolve(at=res_time)
        assert res.status == AlertStatus.RESOLVED
        assert res.acknowledged_at == now
        assert res.resolved_at == res_time
        assert res.is_resolved is True

        # RESOLVED -> OPEN (reopen)
        reopened = res.reopen()
        assert reopened.status == AlertStatus.OPEN
        assert reopened.acknowledged_at is None
        assert reopened.resolved_at is None
        assert reopened.is_open is True

        # ACKNOWLEDGED -> OPEN (unacknowledge)
        ack2 = AlertLifecycle().acknowledge(at=now)
        unack = ack2.unacknowledge()
        assert unack.status == AlertStatus.OPEN
        assert unack.acknowledged_at is None

    def test_lifecycle_invalid_timestamp_order_raises(self) -> None:
        now = datetime.now(UTC)
        earlier = now - timedelta(minutes=5)
        with pytest.raises(ValueError, match="cannot be earlier than acknowledged_at"):
            AlertLifecycle(
                status=AlertStatus.RESOLVED,
                acknowledged_at=now,
                resolved_at=earlier,
            )


class TestTransitionHelpers:
    def test_acknowledge_and_resolve_helpers(self) -> None:
        from app.detection.alerts import (
            acknowledge_alert,
            reopen_alert,
            resolve_alert,
            unacknowledge_alert,
        )

        lc = AlertLifecycle()
        t1 = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
        t2 = datetime(2026, 9, 4, 12, 5, tzinfo=UTC)

        ack = acknowledge_alert(lc, at=t1)
        assert ack.status == AlertStatus.ACKNOWLEDGED
        assert ack.acknowledged_at == t1

        res = resolve_alert(ack, at=t2)
        assert res.status == AlertStatus.RESOLVED
        assert res.resolved_at == t2

        reopened = reopen_alert(res)
        assert reopened.status == AlertStatus.OPEN
        assert reopened.acknowledged_at is None
        assert reopened.resolved_at is None

        ack2 = acknowledge_alert(AlertLifecycle(), at=t1)
        unack = unacknowledge_alert(ack2)
        assert unack.status == AlertStatus.OPEN


class TestSecurityAlertRecordLifecycle:
    def test_to_lifecycle_and_status_enum(self) -> None:
        from app.models.security_alert import SecurityAlertRecord

        ack_time = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
        record = SecurityAlertRecord(
            id=1,
            host_id=1,
            scan_id=1,
            alert_type="new_open_port",
            severity="high",
            message="Port opened",
            port=80,
            status="ACKNOWLEDGED",
            acknowledged_at=ack_time,
            resolved_at=None,
            created_at=datetime.now(UTC),
        )

        assert record.status_enum == AlertStatus.ACKNOWLEDGED
        lifecycle = record.to_lifecycle()
        assert isinstance(lifecycle, AlertLifecycle)
        assert lifecycle.status == AlertStatus.ACKNOWLEDGED
        assert lifecycle.acknowledged_at == ack_time
        assert lifecycle.resolved_at is None
        assert lifecycle.is_acknowledged is True
