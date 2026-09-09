"""Unit tests for WebhookNotificationSender (NetSentinel v0.6.0)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from app.core.config import Settings
from app.detection.alerts import AlertStatus, AlertType, SecurityAlert, Severity
from app.monitoring.target import NetworkTarget
from app.notifications.models import Notification, NotificationChannel
from app.notifications.webhook import (
    WebhookNotificationSender,
    sanitize_text,
    sanitize_url_for_logging,
    validate_webhook_url,
)


@pytest.fixture
def sample_alert() -> SecurityAlert:
    """Fixture providing a deterministic SecurityAlert."""
    return SecurityAlert(
        alert_type=AlertType.NEW_OPEN_PORT,
        severity=Severity.HIGH,
        target=NetworkTarget.parse("192.168.1.50"),
        timestamp=datetime(2026, 9, 9, 15, 30, 0, tzinfo=UTC),
        message="New open TCP port 8080 detected on 192.168.1.50.",
        port=8080,
        source_event_type="port_opened",
        status=AlertStatus.OPEN,
    )


# ---------------------------------------------------------------------------
# URL and Timeout Validation Tests
# ---------------------------------------------------------------------------


class TestWebhookValidation:
    def test_valid_http_and_https_urls(self) -> None:
        assert (
            validate_webhook_url("https://hooks.slack.com/services/123")
            == "https://hooks.slack.com/services/123"
        )
        assert (
            validate_webhook_url("http://127.0.0.1:8000/webhook")
            == "http://127.0.0.1:8000/webhook"
        )

    @pytest.mark.parametrize(
        "invalid_url",
        [
            "",
            "   ",
            "ftp://example.com/alerts",
            "file:///etc/passwd",
            "not-a-valid-url",
            "http://",
            "https://",
            "//missing-scheme.com",
            "https://user:password@example.com/alerts",
            "http://admin:secret@127.0.0.1:8000/webhook",
        ],
    )
    def test_invalid_urls_raise_value_error(self, invalid_url: str) -> None:
        with pytest.raises(ValueError, match="Invalid webhook URL|cannot be empty"):
            validate_webhook_url(invalid_url)

        with pytest.raises(ValueError, match="Invalid webhook URL|cannot be empty"):
            WebhookNotificationSender(url=invalid_url)

    def test_invalid_timeout_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="timeout must be greater than zero"):
            WebhookNotificationSender("https://example.com", timeout=0)

        with pytest.raises(ValueError, match="timeout must be greater than zero"):
            WebhookNotificationSender("https://example.com", timeout=-5.0)


# ---------------------------------------------------------------------------
# Sanitization Tests
# ---------------------------------------------------------------------------


class TestWebhookSanitization:
    def test_sanitize_text_removes_ansi_and_control_chars(self) -> None:
        raw = "\x1b[31m[CRITICAL]\x1b[0m Alert!\x00\x07\x1f \nValid message\t"
        cleaned = sanitize_text(raw)
        assert "\x1b" not in cleaned
        assert "\x00" not in cleaned
        assert "\x07" not in cleaned
        assert "[CRITICAL] Alert! \nValid message" in cleaned

    def test_sanitize_url_for_logging_masks_query_tokens(self) -> None:
        raw_url = "https://hooks.example.com/alert?token=secret123&key=xyz"
        safe = sanitize_url_for_logging(raw_url)
        assert "secret123" not in safe
        assert "xyz" not in safe
        assert safe == "https://hooks.example.com/alert?***"

    def test_sanitize_url_without_query_preserves_url(self) -> None:
        raw_url = "https://hooks.example.com/alert/v1"
        assert sanitize_url_for_logging(raw_url) == "https://hooks.example.com/alert/v1"


# ---------------------------------------------------------------------------
# Stable Payload Tests
# ---------------------------------------------------------------------------


class TestWebhookPayload:
    def test_build_payload_contains_all_stable_fields(
        self, sample_alert: SecurityAlert
    ) -> None:
        sender = WebhookNotificationSender("https://example.com/webhook")
        notif = Notification.from_alert(sample_alert, NotificationChannel.WEBHOOK)
        payload = sender.build_payload(notif)

        assert payload["id"] == notif.id
        assert payload["title"] == "[HIGH] New Open Port on 192.168.1.50"
        assert payload["message"] == "New open TCP port 8080 detected on 192.168.1.50."
        assert payload["severity"] == "high"
        assert payload["alert_type"] == "new_open_port"
        assert payload["target"] == "192.168.1.50"
        assert payload["port"] == 8080
        assert payload["channel"] == "webhook"
        assert payload["timestamp"] == "2026-09-09T15:30:00+00:00"
        assert payload["metadata"]["source_event_type"] == "port_opened"
        assert payload["metadata"]["status"] == "OPEN"

    def test_build_payload_sanitizes_title_and_message(
        self, sample_alert: SecurityAlert
    ) -> None:
        sender = WebhookNotificationSender("https://example.com/webhook")
        notif = Notification(
            id="test-id",
            alert_type="new_open_port",
            severity="high",
            target_address="10.0.0.1",
            title="\x1b[32mClean Title\x1b[0m\x00",
            message="\x1b[1mMalicious \x07Body\x1b[0m",
            channel=NotificationChannel.WEBHOOK,
            timestamp=datetime.now(UTC),
        )
        payload = sender.build_payload(notif)
        assert payload["title"] == "Clean Title"
        assert payload["message"] == "Malicious Body"


# ---------------------------------------------------------------------------
# Async HTTP Delivery Tests (Offline with MockTransport)
# ---------------------------------------------------------------------------


class TestWebhookDelivery:
    @pytest.mark.asyncio
    async def test_successful_delivery_200_and_204(
        self, sample_alert: SecurityAlert
    ) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(204)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            sender = WebhookNotificationSender(
                "https://api.example.com/v1/notify", client=client
            )
            notif = Notification.from_alert(sample_alert, NotificationChannel.WEBHOOK)
            result = await sender.send(notif)

        assert result.success is True
        assert result.channel == NotificationChannel.WEBHOOK
        assert result.delivered_at is not None
        assert result.error_message is None

        assert len(captured) == 1
        req = captured[0]
        assert req.method == "POST"
        assert str(req.url) == "https://api.example.com/v1/notify"
        assert req.headers["content-type"] == "application/json"
        assert req.headers["user-agent"] == "NetSentinel-Notifier/0.6.0"

        decoded = json.loads(req.content.decode("utf-8"))
        assert decoded["id"] == notif.id
        assert decoded["severity"] == "high"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [400, 401, 403, 404, 500, 502, 503])
    async def test_http_error_responses(
        self, sample_alert: SecurityAlert, status_code: int
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code, text="Error body containing sensitive info"
            )

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            sender = WebhookNotificationSender(
                "https://api.example.com/v1/notify?token=fake-secret", client=client
            )
            notif = Notification.from_alert(sample_alert, NotificationChannel.WEBHOOK)
            result = await sender.send(notif)

        assert result.success is False
        assert result.error_message == f"Webhook returned HTTP {status_code}."
        # Sensitive query string and response body are never exposed
        assert "fake-secret" not in (result.error_message or "")
        assert "sensitive info" not in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_redirect_not_followed(self, sample_alert: SecurityAlert) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                302, headers={"Location": "https://evil.example.com/sink"}
            )

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, follow_redirects=False
        ) as client:
            sender = WebhookNotificationSender(
                "https://api.example.com/notify", client=client
            )
            notif = Notification.from_alert(sample_alert, NotificationChannel.WEBHOOK)
            result = await sender.send(notif)

        assert result.success is False
        assert result.error_message == "Webhook returned HTTP 302."

    @pytest.mark.asyncio
    async def test_timeout_exception_handling(
        self, sample_alert: SecurityAlert
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("Connection timed out", request=request)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            sender = WebhookNotificationSender(
                "https://api.example.com/notify?token=fake-secret",
                timeout=3.0,
                client=client,
            )
            notif = Notification.from_alert(sample_alert, NotificationChannel.WEBHOOK)
            result = await sender.send(notif)

        assert result.success is False
        assert result.error_message == "Webhook timeout: request timed out."
        assert "fake-secret" not in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_network_connection_error_handling(
        self, sample_alert: SecurityAlert
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Network is unreachable", request=request)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            sender = WebhookNotificationSender(
                "https://api.example.com/notify?token=fake-secret", client=client
            )
            notif = Notification.from_alert(sample_alert, NotificationChannel.WEBHOOK)
            result = await sender.send(notif)

        assert result.success is False
        assert result.error_message == "Webhook network error."
        assert "fake-secret" not in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_unexpected_exception_handling(
        self, sample_alert: SecurityAlert
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise RuntimeError("Unexpected internal crash")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            sender = WebhookNotificationSender(
                "https://api.example.com/notify", client=client
            )
            notif = Notification.from_alert(sample_alert, NotificationChannel.WEBHOOK)
            result = await sender.send(notif)

        assert result.success is False
        assert result.error_message == "Unexpected webhook delivery error."


# ---------------------------------------------------------------------------
# Configuration Integration Tests
# ---------------------------------------------------------------------------


class TestWebhookConfigurationIntegration:
    def test_settings_empty_webhook_url_returns_none(self) -> None:
        settings = Settings(NOTIFICATION_WEBHOOK_URL="")
        assert settings.get_webhook_sender() is None

        settings_whitespace = Settings(NOTIFICATION_WEBHOOK_URL="   ")
        assert settings_whitespace.get_webhook_sender() is None

    def test_settings_configured_webhook_url_constructs_sender(self) -> None:
        settings = Settings(
            NOTIFICATION_WEBHOOK_URL="https://example.com/webhook",
            NOTIFICATION_WEBHOOK_TIMEOUT=12.5,
        )
        sender = settings.get_webhook_sender()
        assert sender is not None
        assert isinstance(sender, WebhookNotificationSender)
        assert sender.url == "https://example.com/webhook"
        assert sender.timeout == 12.5
