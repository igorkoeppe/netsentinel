"""Dashboard summary response schemas."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class HostsSummary(BaseModel):
    """Aggregated host inventory metrics."""

    model_config = ConfigDict(extra="forbid")

    total: int = Field(..., description="Total number of registered hosts")
    enabled: int = Field(..., description="Active monitored hosts")
    disabled: int = Field(..., description="Disabled hosts")


class ScansSummary(BaseModel):
    """Aggregated scan execution metrics."""

    model_config = ConfigDict(extra="forbid")

    total: int = Field(..., description="Total scans executed")
    last_scan_at: datetime | None = Field(
        None, description="Timestamp of the most recently initiated scan"
    )

    @field_serializer("last_scan_at")
    def serialize_datetime(self, dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return _ensure_utc(dt).isoformat()  # type: ignore[union-attr]


class AlertsSummary(BaseModel):
    """Aggregated alert status and severity metrics."""

    model_config = ConfigDict(extra="forbid")

    total: int = Field(..., description="Total security alerts")
    by_status: dict[str, int] = Field(..., description="Alert counts by status")
    by_severity: dict[str, int] = Field(..., description="Alert counts by severity")


class DashboardSummaryResponse(BaseModel):
    """Combined dashboard summary metrics."""

    model_config = ConfigDict(extra="forbid")

    hosts: HostsSummary = Field(..., description="Host inventory summary")
    scans: ScansSummary = Field(..., description="Scan execution summary")
    alerts: AlertsSummary = Field(..., description="Alert status and severity summary")
