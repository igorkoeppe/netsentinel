"""Scan schedule API schemas."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.services.scan_schedule import DEFAULT_SCHEDULE_INTERVAL, MAX_SCHEDULE_PORTS


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class ScheduleResponse(BaseModel):
    """Periodic scan configured for a host."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="Unique schedule identifier")
    host_id: int = Field(..., description="Scheduled host identifier")
    target: str = Field(..., description="Host network address")
    name: str | None = Field(None, description="Optional host label")
    ports: list[int] = Field(..., description="TCP ports scanned on every run")
    interval_seconds: int = Field(..., description="Seconds between runs")
    enabled: bool = Field(..., description="Whether the schedule is active")
    next_run_at: datetime = Field(..., description="When the next run is due")
    last_run_at: datetime | None = Field(None, description="When it last ran")
    last_scan_id: int | None = Field(
        None, description="Scan produced by the last successful run"
    )
    last_error: str | None = Field(
        None, description="Error of the last run, or null if it succeeded"
    )
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime | None = Field(None, description="Last update timestamp")

    @field_serializer("next_run_at", "last_run_at", "created_at", "updated_at")
    def serialize_datetime(self, dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return _ensure_utc(dt).isoformat()  # type: ignore[union-attr]


class ScheduleCreateRequest(BaseModel):
    """Body of ``POST /schedules``."""

    model_config = ConfigDict(extra="forbid")

    target: str = Field(
        ..., min_length=1, max_length=255, description="IP address or hostname"
    )
    ports: list[int] = Field(
        ...,
        min_length=1,
        max_length=MAX_SCHEDULE_PORTS,
        description=f"Explicit TCP ports (at most {MAX_SCHEDULE_PORTS})",
    )
    interval_seconds: int = Field(
        DEFAULT_SCHEDULE_INTERVAL,
        gt=0,
        description="Seconds between runs (at least SCHEDULE_MIN_INTERVAL)",
    )
    enabled: bool = Field(True, description="Start the schedule enabled")


class ScheduleUpdateRequest(BaseModel):
    """Body of ``PATCH /schedules/{id}``; omitted fields are unchanged."""

    model_config = ConfigDict(extra="forbid")

    ports: list[int] | None = Field(
        None, min_length=1, max_length=MAX_SCHEDULE_PORTS, description="New ports"
    )
    interval_seconds: int | None = Field(None, gt=0, description="New interval")
    enabled: bool | None = Field(None, description="Enable or disable")
