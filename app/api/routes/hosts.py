"""Monitored hosts and host history endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session, require_read_auth
from app.api.errors import APIError
from app.api.schemas.common import PaginatedResponse
from app.api.schemas.hosts import HostHistoryResponse, HostResponse, ScanHistoryItem
from app.monitoring.target import InvalidTargetError, NetworkTarget
from app.services.history import HistoryService
from app.services.host_query import HostQueryService

router = APIRouter(
    prefix="/hosts",
    tags=["Hosts"],
    dependencies=[Depends(require_read_auth)],
)


@router.get(
    "",
    summary="List hosts",
    description="List registered monitored hosts with simple pagination.",
    response_model=PaginatedResponse[HostResponse],
)
async def list_hosts(
    limit: int = Query(
        default=20, ge=1, le=100, description="Items per page (max 100)"
    ),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    enabled: bool | None = Query(default=None, description="Filter by active status"),
    q: str | None = Query(
        default=None, description="Search by name or address substring"
    ),
    session: AsyncSession = Depends(get_session),
) -> PaginatedResponse[HostResponse]:
    service = HostQueryService(session)
    hosts = await service.list_hosts(limit=limit, offset=offset, enabled=enabled, q=q)
    items = [
        HostResponse(
            id=h.id,
            name=h.name,
            address=h.address,
            enabled=h.enabled,
            created_at=h.created_at,
            updated_at=h.updated_at,
        )
        for h in hosts
    ]
    return PaginatedResponse(
        items=items,
        limit=limit,
        offset=offset,
        count=len(items),
    )


@router.get(
    "/{target}/history",
    summary="Get host monitoring history",
    description="Retrieve recent monitoring scans and summaries for a specific host.",
    response_model=HostHistoryResponse,
)
async def get_host_history(
    target: str,
    limit: int = Query(
        default=20, ge=1, le=100, description="Maximum scans to return (max 100)"
    ),
    session: AsyncSession = Depends(get_session),
) -> HostHistoryResponse:
    try:
        parsed_target = NetworkTarget.parse(target)
    except InvalidTargetError:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="HOST_NOT_FOUND",
            message=f"Host '{target}' not found.",
        ) from None

    service = HistoryService(session)
    result = await service.get_host_history(address=parsed_target.value, limit=limit)
    if result is None:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="HOST_NOT_FOUND",
            message=f"Host '{target}' not found.",
        )

    scans = [
        ScanHistoryItem(
            scan_id=s.scan_id,
            started_at=s.timestamp,
            status=s.status,
            response_time_ms=s.response_time_ms,
            port_count=s.port_count,
            event_count=s.event_count,
            alert_count=s.alert_count,
        )
        for s in result.scans
    ]
    return HostHistoryResponse(
        host_id=result.host_id,
        address=result.address,
        name=result.name,
        enabled=result.enabled,
        scans=scans,
    )
