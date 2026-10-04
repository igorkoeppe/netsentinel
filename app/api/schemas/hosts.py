"""Host response schemas."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class HostResponse(BaseModel):
    """Monitored host representation."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="Unique host identifier")
    name: str | None = Field(None, description="Optional human-readable host name")
    address: str = Field(..., description="Network address or hostname")
    enabled: bool = Field(
        ..., description="Whether monitoring is enabled for this host"
    )
    created_at: datetime = Field(..., description="Creation timestamp in ISO 8601")
    updated_at: datetime | None = Field(None, description="Last update timestamp")

    @field_serializer("created_at", "updated_at")
    def serialize_datetime(self, dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return _ensure_utc(dt).isoformat()  # type: ignore[union-attr]


class ScanHistoryItem(BaseModel):
    """Summary of a past scan for host history."""

    model_config = ConfigDict(extra="forbid")

    scan_id: int = Field(..., description="Unique scan identifier")
    started_at: datetime = Field(..., description="Timestamp when scan began")
    status: str = Field(..., description="Host status (e.g. AVAILABLE, UNAVAILABLE)")
    response_time_ms: float | None = Field(
        None, description="Response time in milliseconds"
    )
    port_count: int | None = Field(None, description="Number of ports probed")
    event_count: int | None = Field(None, description="Number of events detected")
    alert_count: int | None = Field(
        None, description="Number of security alerts generated"
    )

    @field_serializer("started_at")
    def serialize_datetime(self, dt: datetime) -> str:
        return _ensure_utc(dt).isoformat()  # type: ignore[union-attr]


class HostHistoryResponse(BaseModel):
    """Host monitoring history representation."""

    model_config = ConfigDict(extra="forbid")

    host_id: int = Field(..., description="Host ID")
    address: str = Field(..., description="Host network address")
    name: str | None = Field(None, description="Host label")
    enabled: bool = Field(..., description="Monitoring status")
    scans: list[ScanHistoryItem] = Field(..., description="Recent scans for this host")
