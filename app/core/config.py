from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.detection.alerts import Severity

if TYPE_CHECKING:
    from app.detection.rules import AlertPolicy


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


settings = Settings()
