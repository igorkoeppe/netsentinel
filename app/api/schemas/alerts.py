"""Security alert API schemas."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class AlertResponse(BaseModel):
    """Security alert item representation."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="Unique alert identifier")
    alert_type: str = Field(..., description="Alert classification type")
    severity: str = Field(
        ..., description="Defensive severity level: INFO, LOW, MEDIUM, HIGH, CRITICAL"
    )
    status: str = Field(..., description="Triage status: OPEN, ACKNOWLEDGED, RESOLVED")
    target: str = Field(..., description="Target network address")
    port: int | None = Field(
        None, description="Associated TCP port, or null for host-level alerts"
    )
    message: str = Field(..., description="Descriptive alert message")
    created_at: datetime = Field(
        ..., description="Timestamp when the alert was created"
    )
    acknowledged_at: datetime | None = Field(
        None, description="Timestamp when acknowledged"
    )
    resolved_at: datetime | None = Field(None, description="Timestamp when resolved")

    @field_serializer("created_at", "acknowledged_at", "resolved_at")
    def serialize_datetime(self, dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return _ensure_utc(dt).isoformat()  # type: ignore[union-attr]


class AlertSummaryResponse(BaseModel):
    """Aggregated alert metrics for dashboards and monitoring."""

    model_config = ConfigDict(extra="forbid")

    total: int = Field(..., description="Total count of security alerts")
    by_status: dict[str, int] = Field(..., description="Alert count grouped by status")
    by_severity: dict[str, int] = Field(
        ..., description="Alert count grouped by severity"
    )
