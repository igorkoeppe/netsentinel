"""Scan details response schemas."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class PortResultResponse(BaseModel):
    """Port probe outcome within a scan."""

    model_config = ConfigDict(extra="forbid")

    port: int = Field(..., description="TCP port number")
    status: str = Field(..., description="Port status (e.g. OPEN, CLOSED, TIMEOUT)")
    response_time_ms: float | None = Field(
        None, description="Probe duration in milliseconds"
    )


class MonitoringEventResponse(BaseModel):
    """Observed state change event within a scan."""

    model_config = ConfigDict(extra="forbid")

    event_type: str = Field(..., description="Classification of the state change")
    port: int | None = Field(None, description="Port involved in the event")
    previous_state: str | None = Field(None, description="Previous state")
    current_state: str | None = Field(None, description="New state")
    created_at: datetime = Field(..., description="Timestamp of the event")

    @field_serializer("created_at")
    def serialize_datetime(self, dt: datetime) -> str:
        return _ensure_utc(dt).isoformat()  # type: ignore[union-attr]


class ScanAlertResponse(BaseModel):
    """Security alert generated within a scan."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="Alert ID")
    alert_type: str = Field(..., description="Alert rule classification")
    severity: str = Field(
        ..., description="Defensive severity level (INFO, LOW, MEDIUM, HIGH, CRITICAL)"
    )
    message: str = Field(..., description="Description of the alert")
    port: int | None = Field(None, description="Port involved")
    created_at: datetime = Field(..., description="Creation timestamp")
    monitoring_event_id: int | None = Field(
        None, description="Source monitoring event ID"
    )

    @field_serializer("created_at")
    def serialize_datetime(self, dt: datetime) -> str:
        return _ensure_utc(dt).isoformat()  # type: ignore[union-attr]


class ScanDetailsResponse(BaseModel):
    """Detailed information for a specific scan."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="Scan identifier")
    target: str | None = Field(None, description="Network address of the target host")
    status: str = Field(..., description="Overall host status during this scan")
    started_at: datetime = Field(..., description="Timestamp when scan began")
    finished_at: datetime | None = Field(
        None, description="Timestamp when scan completed"
    )
    response_time_ms: float | None = Field(
        None, description="Host response time in milliseconds"
    )
    ports: list[PortResultResponse] = Field(
        default_factory=list, description="Port probe results"
    )
    events: list[MonitoringEventResponse] = Field(
        default_factory=list, description="Detected events"
    )
    alerts: list[ScanAlertResponse] = Field(
        default_factory=list, description="Security alerts"
    )

    @field_serializer("started_at", "finished_at")
    def serialize_datetime(self, dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return _ensure_utc(dt).isoformat()  # type: ignore[union-attr]
