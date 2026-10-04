from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.detection.alerts import Severity

if TYPE_CHECKING:
    from app.detection.rules import AlertPolicy
    from app.notifications.policy import NotificationPolicy
    from app.notifications.webhook import WebhookNotificationSender


def _parse_severity(value: Severity | str, setting_name: str) -> Severity:
    """Validate and normalize a severity string or enum into a Severity enum.

    Raises ValueError with a descriptive message if invalid.
    """
    if isinstance(value, Severity):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        try:
            return Severity(normalized)
        except ValueError:
            pass
    raise ValueError(
        f"Invalid alert severity for {setting_name}: '{value}'. "
        f"Must be one of: {', '.join(s.name for s in Severity)}"
    )


def _parse_expected_tcp_ports(value: str | None) -> frozenset[int] | None:
    """Parse comma-separated TCP ports string into a frozenset of integers.

    Returns None if value is None or empty/whitespace (policy disabled).
    Raises ValueError with a clear message on invalid items (non-integers,
    empty items like '22,,443', or ports outside 1..65535).
    """
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None

    ports: set[int] = set()
    for item in cleaned.split(","):
        port_str = item.strip()
        if not port_str:
            raise ValueError(
                "Invalid expected TCP ports: empty port item in list. "
                "Ports must be comma-separated integers between 1 and 65535."
            )
        try:
            port = int(port_str)
        except ValueError:
            raise ValueError(
                f"Invalid expected TCP port: '{port_str}'. "
                "Port must be an integer between 1 and 65535."
            ) from None
        if not (1 <= port <= 65535):
            raise ValueError(
                f"Invalid expected TCP port: '{port_str}'. "
                "Port must be between 1 and 65535."
            )
        ports.add(port)

    return frozenset(ports)


_ALLOWED_CORS_SCHEMES = ("http://", "https://")


def _parse_cors_origins(value: str | None) -> list[str]:
    """Parse a comma-separated list of explicit CORS origins.

    - Empty/whitespace input is valid and disables CORS (returns ``[]``).
    - Items are trimmed, a trailing ``/`` is removed and duplicates are
      dropped while preserving order.
    - ``*`` is rejected: only explicit, trusted origins are allowed.
    - No DNS resolution or network access is performed.
    """
    if value is None or not value.strip():
        return []

    origins: list[str] = []
    for item in value.split(","):
        origin = item.strip().rstrip("/")
        if not origin:
            continue
        if origin == "*":
            raise ValueError(
                "Invalid API_CORS_ORIGINS: wildcard '*' is not allowed; "
                "list explicit trusted origins instead."
            )
        if not origin.lower().startswith(_ALLOWED_CORS_SCHEMES) or any(
            ch.isspace() for ch in origin
        ):
            raise ValueError(
                "Invalid API_CORS_ORIGINS entry: origins must look like "
                "'http://host[:port]' or 'https://host[:port]'."
            )
        origins.append(origin)

    return list(dict.fromkeys(origins))


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # The shared .env also contains Compose-only database credentials.
        extra="ignore",
    )

    APP_NAME: str = "NetSentinel"
    LOG_LEVEL: str = "INFO"

    # Scanning defaults — conservative values for safe operation.
    SCAN_TIMEOUT: float = Field(default=3.0, gt=0, allow_inf_nan=False)
    SCAN_MAX_CONCURRENCY: int = Field(default=50, gt=0)
    MONITOR_INTERVAL: int = Field(default=30, gt=0)

    # Database (v0.3) — empty string means "not configured".
    # The application continues to function without a database for scan/monitor.
    DATABASE_URL: str = ""
    # Schema administration uses a separate credential from the runtime role.
    MIGRATION_DATABASE_URL: str = ""

    # Alert severity rules (v0.4.0) — configured via env vars, validated lazily
    ALERT_SEVERITY_NEW_OPEN_PORT: str = "HIGH"
    ALERT_SEVERITY_PORT_CLOSED: str = "LOW"
    ALERT_SEVERITY_HOST_DOWN: str = "MEDIUM"
    ALERT_SEVERITY_HOST_RECOVERED: str = "INFO"

    # Expected TCP ports policy (v0.4.0)
    EXPECTED_TCP_PORTS: str = ""
    ALERT_SEVERITY_EXPECTED_OPEN_PORT: str = "INFO"
    ALERT_SEVERITY_UNEXPECTED_OPEN_PORT: str = "HIGH"

    # Notifications policy (v0.6.0)
    NOTIFICATION_MIN_SEVERITY: str = "HIGH"

    # Webhook notification delivery (v0.6.0)
    NOTIFICATION_WEBHOOK_URL: str = ""
    NOTIFICATION_WEBHOOK_TIMEOUT: float = Field(default=5.0, gt=0, allow_inf_nan=False)

    # REST API (v0.7.0)
    # Empty API_KEY: read endpoints are open (local development) and mutation
    # endpoints are disabled. SecretStr keeps the value out of reprs/logs.
    API_KEY: SecretStr = SecretStr("")
    # Comma-separated explicit origins. Empty means CORS is not enabled.
    API_CORS_ORIGINS: str = ""

    def get_alert_policy(self) -> AlertPolicy:
        """Construct and validate the AlertPolicy from configured severity settings.

        Lazy validation ensures commands like `netsentinel --help` or
        `netsentinel scan` are not blocked by invalid alert severity variables.
        """
        from app.detection.rules import AlertPolicy

        return AlertPolicy(
            new_open_port_severity=_parse_severity(
                self.ALERT_SEVERITY_NEW_OPEN_PORT, "ALERT_SEVERITY_NEW_OPEN_PORT"
            ),
            port_closed_severity=_parse_severity(
                self.ALERT_SEVERITY_PORT_CLOSED, "ALERT_SEVERITY_PORT_CLOSED"
            ),
            host_down_severity=_parse_severity(
                self.ALERT_SEVERITY_HOST_DOWN, "ALERT_SEVERITY_HOST_DOWN"
            ),
            host_recovered_severity=_parse_severity(
                self.ALERT_SEVERITY_HOST_RECOVERED, "ALERT_SEVERITY_HOST_RECOVERED"
            ),
            expected_tcp_ports=_parse_expected_tcp_ports(self.EXPECTED_TCP_PORTS),
            expected_open_port_severity=_parse_severity(
                self.ALERT_SEVERITY_EXPECTED_OPEN_PORT,
                "ALERT_SEVERITY_EXPECTED_OPEN_PORT",
            ),
            unexpected_open_port_severity=_parse_severity(
                self.ALERT_SEVERITY_UNEXPECTED_OPEN_PORT,
                "ALERT_SEVERITY_UNEXPECTED_OPEN_PORT",
            ),
        )

    def get_notification_policy(self) -> NotificationPolicy:
        """Construct and validate the NotificationPolicy from configured settings.

        Lazy validation ensures commands are not blocked by invalid notification
        variables until notifications are evaluated.
        """
        from app.notifications.policy import NotificationPolicy

        return NotificationPolicy(
            minimum_severity=_parse_severity(
                self.NOTIFICATION_MIN_SEVERITY, "NOTIFICATION_MIN_SEVERITY"
            )
        )

    def get_webhook_sender(self) -> WebhookNotificationSender | None:
        """Construct WebhookNotificationSender if NOTIFICATION_WEBHOOK_URL is set.

        Returns None if NOTIFICATION_WEBHOOK_URL is empty or whitespace.
        """
        cleaned_url = self.NOTIFICATION_WEBHOOK_URL.strip()
        if not cleaned_url:
            return None
        from app.notifications.webhook import WebhookNotificationSender

        return WebhookNotificationSender(
            url=cleaned_url,
            timeout=self.NOTIFICATION_WEBHOOK_TIMEOUT,
        )

    def get_api_key(self) -> str | None:
        """Return the configured API key, or ``None`` when not configured."""
        configured = self.API_KEY.get_secret_value().strip()
        return configured or None

    def get_cors_origins(self) -> list[str]:
        """Return validated, deduplicated CORS origins (empty = disabled)."""
        return _parse_cors_origins(self.API_CORS_ORIGINS)


settings = Settings()
