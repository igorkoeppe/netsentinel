"""Notification delivery schemas."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class NotificationDeliveryResponse(BaseModel):
    """Sanitized record of an alert notification delivery attempt."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="Unique delivery attempt identifier")
    alert_id: int = Field(..., description="Referenced security alert ID")
    channel: str = Field(..., description="Delivery channel used (e.g. webhook)")
    success: bool = Field(..., description="Whether the delivery succeeded")
    delivered_at: datetime | None = Field(None, description="Confirmation timestamp")
    error: str | None = Field(
        None, description="Sanitized failure reason if unsuccessful"
    )
    created_at: datetime = Field(..., description="Timestamp of the attempt")

    @field_serializer("delivered_at", "created_at")
    def serialize_datetime(self, dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return _ensure_utc(dt).isoformat()  # type: ignore[union-attr]
