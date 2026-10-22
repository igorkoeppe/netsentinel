"""Scan schedule endpoints: list, inspect, create and update periodic scans."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session, require_mutation_auth, require_read_auth
from app.api.errors import APIError
from app.api.schemas.common import PaginatedResponse
from app.api.schemas.schedules import (
    ScheduleCreateRequest,
    ScheduleResponse,
    ScheduleUpdateRequest,
)
from app.services.scan_schedule import (
    InvalidScheduleError,
    ScanScheduleService,
    ScheduleAlreadyExistsError,
    ScheduleItem,
    ScheduleNotFoundError,
)

router = APIRouter(
    prefix="/schedules",
    tags=["Schedules"],
)


def _to_response(item: ScheduleItem) -> ScheduleResponse:
    return ScheduleResponse(
        id=item.id,
        host_id=item.host_id,
        target=item.address,
        name=item.name,
        ports=list(item.ports),
        interval_seconds=item.interval_seconds,
        enabled=item.enabled,
        next_run_at=item.next_run_at,
        last_run_at=item.last_run_at,
        last_scan_id=item.last_scan_id,
        last_error=item.last_error,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _not_found(schedule_id: int) -> APIError:
    return APIError(
        status_code=status.HTTP_404_NOT_FOUND,
        code="SCHEDULE_NOT_FOUND",
        message=f"Schedule {schedule_id} not found.",
    )


def _invalid(exc: InvalidScheduleError) -> APIError:
    return APIError(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        code="VALIDATION_ERROR",
        message=str(exc),
    )


@router.get(
    "",
    summary="List scan schedules",
    description="List periodic scans configured per host.",
    response_model=PaginatedResponse[ScheduleResponse],
    dependencies=[Depends(require_read_auth)],
)
async def list_schedules(
    limit: int = Query(
        default=20, ge=1, le=100, description="Items per page (max 100)"
    ),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    enabled: bool | None = Query(default=None, description="Filter by active state"),
    session: AsyncSession = Depends(get_session),
) -> PaginatedResponse[ScheduleResponse]:
    service = ScanScheduleService(session)
    items = [
        _to_response(s)
        for s in await service.list_schedules(
            limit=limit, offset=offset, enabled=enabled
        )
    ]
    return PaginatedResponse(items=items, limit=limit, offset=offset, count=len(items))


@router.get(
    "/{schedule_id}",
    summary="Get scan schedule",
    response_model=ScheduleResponse,
    dependencies=[Depends(require_read_auth)],
)
async def get_schedule(
    schedule_id: int = Path(..., ge=1, description="Schedule ID"),
    session: AsyncSession = Depends(get_session),
) -> ScheduleResponse:
    try:
        item = await ScanScheduleService(session).get_schedule(schedule_id)
    except ScheduleNotFoundError:
        raise _not_found(schedule_id) from None
    return _to_response(item)


@router.post(
    "",
    summary="Create scan schedule",
    description=(
        "Scan a host periodically. The first run is due immediately; later runs "
        "compare each scan with the previous one and raise alerts for ports "
        "that open or close."
    ),
    response_model=ScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_mutation_auth)],
)
async def create_schedule(
    body: ScheduleCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> ScheduleResponse:
    service = ScanScheduleService(session)
    try:
        item = await service.create_schedule(
            target=body.target,
            ports=body.ports,
            interval_seconds=body.interval_seconds,
            enabled=body.enabled,
            now=datetime.now(UTC),
        )
    except InvalidScheduleError as exc:
        raise _invalid(exc) from None
    except ScheduleAlreadyExistsError:
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            code="SCHEDULE_EXISTS",
            message=f"Host '{body.target}' already has a scan schedule.",
        ) from None
    return _to_response(item)


@router.patch(
    "/{schedule_id}",
    summary="Update scan schedule",
    description="Change ports or interval, or enable/disable a schedule.",
    response_model=ScheduleResponse,
    dependencies=[Depends(require_mutation_auth)],
)
async def update_schedule(
    body: ScheduleUpdateRequest,
    schedule_id: int = Path(..., ge=1, description="Schedule ID"),
    session: AsyncSession = Depends(get_session),
) -> ScheduleResponse:
    service = ScanScheduleService(session)
    try:
        item = await service.update_schedule(
            schedule_id,
            ports=body.ports,
            interval_seconds=body.interval_seconds,
            enabled=body.enabled,
            now=datetime.now(UTC),
        )
    except InvalidScheduleError as exc:
        raise _invalid(exc) from None
    except ScheduleNotFoundError:
        raise _not_found(schedule_id) from None
    return _to_response(item)
