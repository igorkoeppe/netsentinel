"""Asynchronous Webhook notification sender using HTTPX.

Dispatches security notifications via HTTP POST to a configured webhook endpoint
with timeout control, robust error handling, and payload sanitization.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from app.notifications.models import (
    Notification,
    NotificationChannel,
    NotificationResult,
)

logger = logging.getLogger(__name__)

# Remove ANSI escape sequences
_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
# Remove control characters (ASCII 0-31 except \n, \r, \t, and ASCII 127)
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_text(text: str) -> str:
    """Sanitize text by removing ANSI sequences and non-printable control characters."""
    without_ansi = _ANSI_RE.sub("", text)
    cleaned = _CONTROL_CHARS_RE.sub("", without_ansi)
    return cleaned.strip()


def sanitize_url_for_logging(url: str) -> str:
    """Sanitize URL by masking query parameters that might contain tokens/secrets."""
    try:
        parsed = urlparse(url)
        if parsed.query:
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?***"
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    except Exception:
        return "[invalid-url]"


def validate_webhook_url(url: str) -> str:
    """Validate that the URL is a non-empty HTTP or HTTPS URL.

    Raises:
        ValueError: If the URL is empty or does not use http:// or https:// scheme.
    """
    cleaned = url.strip()
    if not cleaned:
        raise ValueError("Webhook URL cannot be empty.")
    try:
        parsed = urlparse(cleaned)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(
                f"Invalid webhook URL: '{cleaned}'. "
                "URL must start with 'http://' or 'https://' and include a host."
            )
        if parsed.username or parsed.password:
            raise ValueError(
                f"Invalid webhook URL: '{cleaned}'. "
                "URL must not contain embedded credentials."
            )
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Invalid webhook URL: '{cleaned}': {exc}") from exc
    return cleaned


class WebhookNotificationSender:
    """Asynchronously sends security alert notifications via HTTP POST using HTTPX.

    Attributes:
        url: Destination webhook URL.
        timeout: Network timeout in seconds (default: 5.0).
    """

    def __init__(
        self,
        url: str,
        *,
        timeout: float = 5.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.url = validate_webhook_url(url)
        if timeout <= 0:
            raise ValueError("Webhook timeout must be greater than zero.")
        self.timeout = timeout
        self._client = client

    def build_payload(self, notification: Notification) -> dict[str, Any]:
        """Construct a stable, sanitized JSON payload from a Notification."""
        sanitized_title = sanitize_text(notification.title)
        sanitized_message = sanitize_text(notification.message)

        return {
            "id": notification.id,
            "title": sanitized_title,
            "message": sanitized_message,
            "severity": notification.severity,
            "alert_type": notification.alert_type,
            "target": notification.target_address,
            "port": notification.port,
            "channel": notification.channel.value,
            "timestamp": notification.timestamp.isoformat(),
            "metadata": notification.metadata,
        }

    async def send(self, notification: Notification) -> NotificationResult:
        """Asynchronously dispatch notification to the webhook endpoint.

        Parameters:
            notification: The Notification to deliver.

        Returns:
            NotificationResult representing the outcome (success or error).
        """
        payload = self.build_payload(notification)
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "NetSentinel-Notifier/0.6.0",
        }
        safe_url = sanitize_url_for_logging(self.url)

        try:
            if self._client is not None:
                response = await self._client.post(
                    self.url,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                )
            else:
                async with httpx.AsyncClient(
                    timeout=self.timeout,
                    follow_redirects=False,
                ) as client:
                    response = await client.post(
                        self.url,
                        json=payload,
                        headers=headers,
                    )

            if response.is_success:
                return NotificationResult(
                    success=True,
                    channel=NotificationChannel.WEBHOOK,
                    notification_id=notification.id,
                    delivered_at=datetime.now(UTC),
                )

            status = response.status_code
            error_msg = f"Webhook returned HTTP {status}."
            logger.warning(
                "Webhook delivery failed with HTTP %d for alert %s to %s",
                status,
                notification.id,
                safe_url,
            )
            return NotificationResult(
                success=False,
                channel=NotificationChannel.WEBHOOK,
                notification_id=notification.id,
                error_message=error_msg,
            )

        except httpx.TimeoutException:
            error_msg = "Webhook timeout: request timed out."
            logger.warning(
                "Webhook delivery timed out for alert %s to %s",
                notification.id,
                safe_url,
            )
            return NotificationResult(
                success=False,
                channel=NotificationChannel.WEBHOOK,
                notification_id=notification.id,
                error_message=error_msg,
            )

        except httpx.RequestError:
            error_msg = "Webhook network error."
            logger.warning(
                "Webhook delivery network error for alert %s to %s",
                notification.id,
                safe_url,
            )
            return NotificationResult(
                success=False,
                channel=NotificationChannel.WEBHOOK,
                notification_id=notification.id,
                error_message=error_msg,
            )

        except Exception as exc:
            error_msg = "Unexpected webhook delivery error."
            logger.error(
                "Unexpected webhook delivery failure for alert %s to %s: %s",
                notification.id,
                safe_url,
                exc,
                exc_info=True,
            )
            return NotificationResult(
                success=False,
                channel=NotificationChannel.WEBHOOK,
                notification_id=notification.id,
                error_message=error_msg,
            )
