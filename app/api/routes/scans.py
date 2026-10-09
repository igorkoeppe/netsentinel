"""Scan details endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session, require_read_auth
from app.api.errors import APIError
from app.api.schemas.common import PaginatedResponse
from app.api.schemas.scans import (
    MonitoringEventResponse,
    PortResultResponse,
    ScanAlertResponse,
    ScanDetailsResponse,
    ScanSummaryResponse,
)
from app.services.history import HistoryService
from app.services.scan_query import ScanQueryService

router = APIRouter(
    prefix="/scans",
    tags=["Scans"],
    dependencies=[Depends(require_read_auth)],
)


@router.get(
    "",
    summary="List scans",
    description=(
        "List global monitoring scans with pagination and optional target filter."
    ),
    response_model=PaginatedResponse[ScanSummaryResponse],
)
async def list_scans(
    limit: int = Query(
        default=20, ge=1, le=100, description="Items per page (max 100)"
    ),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    target: str | None = Query(
        default=None, description="Filter by target host address"
    ),
    session: AsyncSession = Depends(get_session),
) -> PaginatedResponse[ScanSummaryResponse]:
    service = ScanQueryService(session)
    scans = await service.list_scans(limit=limit, offset=offset, target=target)
    items = [
        ScanSummaryResponse(
            id=s.id,
            target=s.target,
            status=s.status.upper(),
            response_time_ms=s.response_time_ms,
            started_at=s.started_at,
            finished_at=s.finished_at,
        )
        for s in scans
    ]
    return PaginatedResponse(
        items=items,
        limit=limit,
        offset=offset,
        count=len(items),
    )


@router.get(
    "/{scan_id}",
    summary="Get scan details",
    description="Retrieve comprehensive details for a specific scan cycle.",
    response_model=ScanDetailsResponse,
)
async def get_scan(
    scan_id: int = Path(..., ge=1, description="Scan ID"),
    session: AsyncSession = Depends(get_session),
) -> ScanDetailsResponse:
    service = HistoryService(session)
    details = await service.get_scan_details(scan_id)
    if details is None:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="SCAN_NOT_FOUND",
            message=f"Scan {scan_id} not found.",
        )

    ports = [
        PortResultResponse(
            port=p.port,
            status=p.status.upper(),
            response_time_ms=p.response_time_ms,
        )
        for p in details.ports
    ]

    events = [
        MonitoringEventResponse(
            event_type=e.event_type.upper(),
            port=e.port,
            previous_state=e.previous_state.upper() if e.previous_state else None,
            current_state=e.current_state.upper() if e.current_state else None,
            created_at=e.created_at,
        )
        for e in details.events
    ]

    alerts = [
        ScanAlertResponse(
            id=a.id,
            alert_type=a.alert_type.upper(),
            severity=a.severity.upper(),
            message=a.message,
            port=a.port,
            created_at=a.created_at,
            monitoring_event_id=a.monitoring_event_id,
        )
        for a in details.alerts
    ]

    return ScanDetailsResponse(
        id=details.scan_id,
        target=details.target,
        status=details.status.upper(),
        started_at=details.started_at,
        finished_at=details.finished_at,
        response_time_ms=details.response_time_ms,
        ports=ports,
        events=events,
        alerts=alerts,
    )
