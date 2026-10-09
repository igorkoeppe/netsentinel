"""Operational dashboard summary endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session, require_read_auth
from app.api.schemas.dashboard import (
    AlertsSummary,
    DashboardSummaryResponse,
    HostsSummary,
    ScansSummary,
)
from app.services.dashboard_query import DashboardQueryService

router = APIRouter(
    prefix="/dashboard",
    tags=["Dashboard"],
    dependencies=[Depends(require_read_auth)],
)


@router.get(
    "/summary",
    summary="Get operational dashboard summary",
    description="Aggregate metrics for hosts, scans, and security alerts.",
    response_model=DashboardSummaryResponse,
)
async def get_dashboard_summary(
    session: AsyncSession = Depends(get_session),
) -> DashboardSummaryResponse:
    service = DashboardQueryService(session)
    summary = await service.get_summary()

    return DashboardSummaryResponse(
        hosts=HostsSummary(
            total=summary.hosts.total,
            enabled=summary.hosts.enabled,
            disabled=summary.hosts.disabled,
        ),
        scans=ScansSummary(
            total=summary.scans.total,
            last_scan_at=summary.scans.last_scan_at,
        ),
        alerts=AlertsSummary(
            total=summary.alerts.total,
            by_status=summary.alerts.by_status,
            by_severity=summary.alerts.by_severity,
        ),
    )
