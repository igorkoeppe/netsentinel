"""Unit tests for NetSentinel alert notification subsystem."""

from __future__ import annotations

import io
import json
import logging
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import httpx
import pytest

from app.detection.alerts import AlertStatus, AlertType, SecurityAlert, Severity
from app.monitoring.target import NetworkTarget
from app.notifications import (
    ConsoleNotificationSender,
    InMemoryNotificationSender,
    LoggingNotificationSender,
    Notification,
    NotificationChannel,
    NotificationDispatcher,
    NotificationResult,
    WebhookNotificationSender,
)


@pytest.fixture
def sample_alert() -> SecurityAlert:
    """Fixture providing a deterministic SecurityAlert."""
    target = NetworkTarget.parse("192.168.1.10")
    return SecurityAlert(
        alert_type=AlertType.NEW_OPEN_PORT,
        severity=Severity.HIGH,
        target=target,
        timestamp=datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC),
        message="New TCP port 443 detected on 192.168.1.10.",
        port=443,
        source_event_type="port_opened",
        status=AlertStatus.OPEN,
    )


# ---------------------------------------------------------------------------
# Notification Domain Model Tests
# ---------------------------------------------------------------------------


class TestNotificationModel:
    def test_from_alert_standard_fields(self, sample_alert: SecurityAlert) -> None:
        notif = Notification.from_alert(sample_alert, NotificationChannel.CONSOLE)

        assert notif.channel == NotificationChannel.CONSOLE
        assert notif.alert_type == "new_open_port"
        assert notif.severity == "high"
        assert notif.target_address == "192.168.1.10"
        assert notif.port == 443
        assert notif.message == "New TCP port 443 detected on 192.168.1.10."
        assert notif.timestamp == datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
        assert notif.title == "[HIGH] New Open Port on 192.168.1.10"
        assert notif.metadata["source_event_type"] == "port_opened"
        assert notif.metadata["status"] == "OPEN"
        assert len(notif.id) > 0

    def test_from_alert_custom_title_and_metadata(
        self, sample_alert: SecurityAlert
    ) -> None:
        notif = Notification.from_alert(
            sample_alert,
            NotificationChannel.LOG,
            title="Custom Alert Title",
            notification_id="fixed-id-123",
            extra_metadata={"environment": "production"},
        )

        assert notif.id == "fixed-id-123"
        assert notif.title == "Custom Alert Title"
        assert notif.metadata["environment"] == "production"
        assert notif.metadata["source_event_type"] == "port_opened"

    def test_from_alert_naive_datetime_normalized_to_utc(self) -> None:
        naive_dt = datetime(2026, 9, 9, 10, 0, 0)
        alert = SecurityAlert(
            alert_type=AlertType.HOST_DOWN,
            severity=Severity.CRITICAL,
            target=NetworkTarget.parse("10.0.0.1"),
            timestamp=naive_dt,
            message="Host went down",
            port=None,
            source_event_type="host_became_unavailable",
        )
        notif = Notification.from_alert(alert, NotificationChannel.IN_MEMORY)
        assert notif.timestamp.tzinfo is not None
        assert notif.port is None

    def test_notification_is_immutable(self, sample_alert: SecurityAlert) -> None:
        notif = Notification.from_alert(sample_alert, NotificationChannel.CONSOLE)
        with pytest.raises(FrozenInstanceError):
            notif.title = "Changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Senders Tests
# ---------------------------------------------------------------------------


class TestInMemoryNotificationSender:
    @pytest.mark.asyncio
    async def test_send_and_inspect(self, sample_alert: SecurityAlert) -> None:
        sender = InMemoryNotificationSender()
        assert sender.count == 0

        notif = Notification.from_alert(sample_alert, NotificationChannel.IN_MEMORY)
        result = await sender.send(notif)

        assert result.success is True
        assert result.channel == NotificationChannel.IN_MEMORY
        assert result.delivered_at is not None
        assert sender.count == 1
        assert sender.notifications[0] == notif

        sender.clear()
        assert sender.count == 0
        assert len(sender.results) == 0


class TestLoggingNotificationSender:
    @pytest.mark.asyncio
    async def test_logging_levels(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        logger = logging.getLogger("test.notifications")
        sender = LoggingNotificationSender(logger=logger)

        severities = [
            (Severity.CRITICAL, logging.CRITICAL),
            (Severity.HIGH, logging.ERROR),
            (Severity.MEDIUM, logging.WARNING),
            (Severity.LOW, logging.INFO),
            (Severity.INFO, logging.INFO),
        ]

        for severity, log_level in severities:
            caplog.clear()
            alert = SecurityAlert(
                alert_type=AlertType.NEW_OPEN_PORT,
                severity=severity,
                target=NetworkTarget.parse("127.0.0.1"),
                timestamp=datetime.now(UTC),
                message=f"Test message for {severity.value}",
                port=80,
                source_event_type="port_opened",
            )
            notif = Notification.from_alert(alert, NotificationChannel.LOG)
            with caplog.at_level(logging.DEBUG, logger="test.notifications"):
                result = await sender.send(notif)

            assert result.success is True
            assert result.channel == NotificationChannel.LOG
            assert len(caplog.records) == 1
            assert caplog.records[0].levelno == log_level
            assert f"Test message for {severity.value}" in caplog.records[0].message


class TestConsoleNotificationSender:
    @pytest.mark.asyncio
    async def test_console_output_formatting(self, sample_alert: SecurityAlert) -> None:
        stream = io.StringIO()
        sender = ConsoleNotificationSender(stream=stream)

        notif = Notification.from_alert(sample_alert, NotificationChannel.CONSOLE)
        result = await sender.send(notif)

        assert result.success is True
        output = stream.getvalue()
        assert "[SECURITY ALERT] HIGH" in output
        assert "Target:  192.168.1.10:443" in output
        assert "Type:    new_open_port" in output
        assert "New TCP port 443 detected on 192.168.1.10." in output


class TestWebhookNotificationSender:
    @pytest.mark.asyncio
    async def test_webhook_success_200(self, sample_alert: SecurityAlert) -> None:
        captured_requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append(request)
            return httpx.Response(200, json={"status": "ok"})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            sender = WebhookNotificationSender(
                url="https://hooks.example.com/alerts",
                client=client,
            )
            notif = Notification.from_alert(sample_alert, NotificationChannel.WEBHOOK)
            result = await sender.send(notif)

        assert result.success is True
        assert result.channel == NotificationChannel.WEBHOOK
        assert len(captured_requests) == 1

        req = captured_requests[0]
        assert str(req.url) == "https://hooks.example.com/alerts"
        assert req.headers["content-type"] == "application/json"

        body = json.loads(req.content.decode("utf-8"))
        assert body["id"] == notif.id
        assert body["target"] == "192.168.1.10"
        assert body["port"] == 443
        assert body["severity"] == "high"

    @pytest.mark.asyncio
    async def test_webhook_http_error_response(
        self, sample_alert: SecurityAlert
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal Server Error")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            sender = WebhookNotificationSender(
                url="https://hooks.example.com/alerts",
                client=client,
            )
            notif = Notification.from_alert(sample_alert, NotificationChannel.WEBHOOK)
            result = await sender.send(notif)

        assert result.success is False
        assert "HTTP 500" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_webhook_timeout_exception(self, sample_alert: SecurityAlert) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("Read timed out", request=request)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            sender = WebhookNotificationSender(
                url="https://hooks.example.com/alerts",
                client=client,
            )
            notif = Notification.from_alert(sample_alert, NotificationChannel.WEBHOOK)
            result = await sender.send(notif)

        assert result.success is False
        assert "timeout" in (result.error_message or "").lower()

    @pytest.mark.asyncio
    async def test_webhook_network_error(self, sample_alert: SecurityAlert) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused", request=request)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            sender = WebhookNotificationSender(
                url="https://hooks.example.com/alerts",
                client=client,
            )
            notif = Notification.from_alert(sample_alert, NotificationChannel.WEBHOOK)
            result = await sender.send(notif)

        assert result.success is False
        assert "network error" in (result.error_message or "").lower()


# ---------------------------------------------------------------------------
# NotificationDispatcher Tests
# ---------------------------------------------------------------------------


class TestNotificationDispatcher:
    @pytest.mark.asyncio
    async def test_dispatch_no_senders_returns_empty(
        self, sample_alert: SecurityAlert
    ) -> None:
        dispatcher = NotificationDispatcher()
        results = await dispatcher.dispatch(sample_alert)
        assert results == []

    @pytest.mark.asyncio
    async def test_dispatch_to_all_registered(
        self, sample_alert: SecurityAlert
    ) -> None:
        dispatcher = NotificationDispatcher()
        in_memory = InMemoryNotificationSender()
        stream = io.StringIO()
        console = ConsoleNotificationSender(stream=stream)

        dispatcher.register(NotificationChannel.IN_MEMORY, in_memory)
        dispatcher.register(NotificationChannel.CONSOLE, console)

        assert set(dispatcher.registered_channels) == {
            NotificationChannel.IN_MEMORY,
            NotificationChannel.CONSOLE,
        }

        results = await dispatcher.dispatch(sample_alert)

        assert len(results) == 2
        assert all(r.success for r in results)
        assert in_memory.count == 1
        assert "New TCP port 443 detected" in stream.getvalue()

    @pytest.mark.asyncio
    async def test_dispatch_to_selective_channels(
        self, sample_alert: SecurityAlert
    ) -> None:
        dispatcher = NotificationDispatcher()
        in_memory = InMemoryNotificationSender()
        stream = io.StringIO()
        console = ConsoleNotificationSender(stream=stream)

        dispatcher.register(NotificationChannel.IN_MEMORY, in_memory)
        dispatcher.register(NotificationChannel.CONSOLE, console)

        # Dispatch only to IN_MEMORY
        results = await dispatcher.dispatch(
            sample_alert, channels=[NotificationChannel.IN_MEMORY]
        )

        assert len(results) == 1
        assert results[0].channel == NotificationChannel.IN_MEMORY
        assert in_memory.count == 1
        assert stream.getvalue() == ""

    @pytest.mark.asyncio
    async def test_unregister_channel(self, sample_alert: SecurityAlert) -> None:
        dispatcher = NotificationDispatcher()
        in_memory = InMemoryNotificationSender()
        dispatcher.register(NotificationChannel.IN_MEMORY, in_memory)

        dispatcher.unregister(NotificationChannel.IN_MEMORY)
        results = await dispatcher.dispatch(sample_alert)

        assert results == []
        assert in_memory.count == 0

    @pytest.mark.asyncio
    async def test_sender_exception_isolation(
        self, sample_alert: SecurityAlert
    ) -> None:
        dispatcher = NotificationDispatcher()
        in_memory = InMemoryNotificationSender()

        class FaultySender:
            async def send(self, notification: Notification) -> NotificationResult:
                raise RuntimeError("Explosive hardware failure!")

        dispatcher.register(NotificationChannel.IN_MEMORY, in_memory)
        dispatcher.register(NotificationChannel.CONSOLE, FaultySender())  # type: ignore[arg-type]

        results = await dispatcher.dispatch(sample_alert)

        assert len(results) == 2
        success_result = next(
            r for r in results if r.channel == NotificationChannel.IN_MEMORY
        )
        failure_result = next(
            r for r in results if r.channel == NotificationChannel.CONSOLE
        )

        assert success_result.success is True
        assert in_memory.count == 1

        assert failure_result.success is False
        assert "Explosive hardware failure" in (failure_result.error_message or "")

    @pytest.mark.asyncio
    async def test_dispatch_many(self, sample_alert: SecurityAlert) -> None:
        dispatcher = NotificationDispatcher()
        in_memory = InMemoryNotificationSender()
        dispatcher.register(NotificationChannel.IN_MEMORY, in_memory)

        alert2 = SecurityAlert(
            alert_type=AlertType.HOST_DOWN,
            severity=Severity.CRITICAL,
            target=NetworkTarget.parse("10.0.0.1"),
            timestamp=datetime.now(UTC),
            message="Host down",
            port=None,
            source_event_type="host_became_unavailable",
        )

        results = await dispatcher.dispatch_many([sample_alert, alert2])

        assert len(results) == 2
        assert all(r.success for r in results)
        assert in_memory.count == 2
        assert in_memory.notifications[0].alert_type == "new_open_port"
        assert in_memory.notifications[1].alert_type == "host_down"
