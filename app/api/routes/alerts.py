"""Security alerts endpoints.

Queue, filters, details, summary, deliveries, and remote triage.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session, require_mutation_auth, require_read_auth
from app.api.errors import APIError
from app.api.schemas.alerts import AlertResponse, AlertSummaryResponse
from app.api.schemas.common import PaginatedResponse
from app.api.schemas.deliveries import NotificationDeliveryResponse
from app.detection.alerts import (
    AlertStatus,
    AlertType,
    InvalidAlertStateTransitionError,
    Severity,
)
from app.monitoring.target import InvalidTargetError, NetworkTarget
from app.repositories.notification_delivery import NotificationDeliveryRepository
from app.services.alert_query import AlertQueryService
from app.services.alert_triage import AlertNotFoundError, AlertTriageService

router = APIRouter(
    prefix="/alerts",
    tags=["Alerts"],
)


def _parse_filter_status(val: str | None) -> AlertStatus | None:
    if val is None or not val.strip():
        return None
    normalized = val.strip().upper()
    try:
        return AlertStatus(normalized)
    except ValueError:
        valid_choices = ", ".join(s.value for s in AlertStatus)
        raise APIError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message=f"Invalid status '{val}'. Valid choices are: {valid_choices}.",
        ) from None


def _parse_filter_severity(val: str | None) -> Severity | None:
    if val is None or not val.strip():
        return None
    normalized = val.strip().lower()
    try:
        return Severity(normalized)
    except ValueError:
        valid_choices = ", ".join(s.name for s in Severity)
        raise APIError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message=f"Invalid severity '{val}'. Valid choices are: {valid_choices}.",
        ) from None


def _parse_filter_type(val: str | None) -> AlertType | None:
    if val is None or not val.strip():
        return None
    cleaned = val.strip()
    try:
        return AlertType(cleaned.lower())
    except ValueError:
        try:
            return AlertType[cleaned.upper()]
        except KeyError:
            valid_choices = ", ".join(t.name for t in AlertType)
            raise APIError(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="VALIDATION_ERROR",
                message=(
                    f"Invalid alert type '{val}'. Valid choices are: {valid_choices}."
                ),
            ) from None


def _normalize_filter_target(val: str | None) -> str | None:
    if val is None or not val.strip():
        return None
    raw = val.strip()
    try:
        return NetworkTarget.parse(raw).value
    except InvalidTargetError:
        return raw


# ---------------------------------------------------------------------------
# Static summary route — MUST precede dynamic /{alert_id} route
# ---------------------------------------------------------------------------


@router.get(
    "/summary",
    summary="Get alert summary metrics",
    description="Aggregate metrics of security alerts grouped by status and severity.",
    response_model=AlertSummaryResponse,
    dependencies=[Depends(require_read_auth)],
)
async def get_alert_summary(
    session: AsyncSession = Depends(get_session),
) -> AlertSummaryResponse:
    service = AlertQueryService(session)
    summary = await service.get_summary()
    return AlertSummaryResponse(
        total=summary["total"],
        by_status=summary["by_status"],
        by_severity=summary["by_severity"],
    )


# ---------------------------------------------------------------------------
# Alert list with filters
# ---------------------------------------------------------------------------


@router.get(
    "",
    summary="List security alerts",
    description=(
        "Query security alerts with optional status, severity, type, and target"
        " filters."
    ),
    response_model=PaginatedResponse[AlertResponse],
    dependencies=[Depends(require_read_auth)],
)
async def list_alerts(
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description="Filter by status (OPEN, ACKNOWLEDGED, RESOLVED)",
    ),
    severity_filter: str | None = Query(
        default=None,
        alias="severity",
        description="Filter by severity (INFO, LOW, MEDIUM, HIGH, CRITICAL)",
    ),
    type_filter: str | None = Query(
        default=None,
        alias="type",
        description="Filter by alert type (e.g. UNEXPECTED_OPEN_PORT)",
    ),
    target_filter: str | None = Query(
        default=None, alias="target", description="Filter by target address"
    ),
    limit: int = Query(default=20, ge=1, le=100, description="Page limit (max 100)"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    session: AsyncSession = Depends(get_session),
) -> PaginatedResponse[AlertResponse]:
    status_enum = _parse_filter_status(status_filter)
    severity_enum = _parse_filter_severity(severity_filter)
    type_enum = _parse_filter_type(type_filter)
    target_str = _normalize_filter_target(target_filter)

    service = AlertQueryService(session)
    records = await service.list_alerts(
        limit=limit,
        offset=offset,
        status=status_enum,
        severity=severity_enum,
        alert_type=type_enum,
        target=target_str,
    )

    items = [
        AlertResponse(
            id=r.id,
            alert_type=r.alert_type.upper(),
            severity=r.severity.upper(),
            status=r.status.upper(),
            target=r.target,
            port=r.port,
            message=r.message or r.alert_type,
            created_at=r.created_at,
            acknowledged_at=r.acknowledged_at,
            resolved_at=r.resolved_at,
        )
        for r in records
    ]

    return PaginatedResponse(
        items=items,
        limit=limit,
        offset=offset,
        count=len(items),
    )


# ---------------------------------------------------------------------------
# Alert details
# ---------------------------------------------------------------------------


@router.get(
    "/{alert_id}",
    summary="Get alert details",
    description="Retrieve full details of a specific security alert.",
    response_model=AlertResponse,
    dependencies=[Depends(require_read_auth)],
)
async def get_alert(
    alert_id: int = Path(..., ge=1, description="Alert ID"),
    session: AsyncSession = Depends(get_session),
) -> AlertResponse:
    service = AlertQueryService(session)
    record = await service.get_alert(alert_id)
    if record is None:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="ALERT_NOT_FOUND",
            message=f"Alert {alert_id} not found.",
        )

    return AlertResponse(
        id=record.id,
        alert_type=record.alert_type.upper(),
        severity=record.severity.upper(),
        status=record.status.upper(),
        target=record.target,
        port=record.port,
        message=record.message or record.alert_type,
        created_at=record.created_at,
        acknowledged_at=record.acknowledged_at,
        resolved_at=record.resolved_at,
    )


# ---------------------------------------------------------------------------
# Alert delivery history
# ---------------------------------------------------------------------------


@router.get(
    "/{alert_id}/deliveries",
    summary="Get alert notification deliveries",
    description=(
        "List notification dispatch attempts and outcomes for a specific alert."
    ),
    response_model=PaginatedResponse[NotificationDeliveryResponse],
    dependencies=[Depends(require_read_auth)],
)
async def get_alert_deliveries(
    alert_id: int = Path(..., ge=1, description="Alert ID"),
    session: AsyncSession = Depends(get_session),
) -> PaginatedResponse[NotificationDeliveryResponse]:
    # Confirm alert exists first
    query_service = AlertQueryService(session)
    alert = await query_service.get_alert(alert_id)
    if alert is None:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="ALERT_NOT_FOUND",
            message=f"Alert {alert_id} not found.",
        )

    delivery_repo = NotificationDeliveryRepository(session)
    records = await delivery_repo.list_by_alert(alert_id)

    items = [
        NotificationDeliveryResponse(
            id=d.id,
            alert_id=d.alert_id,
            channel=d.channel,
            success=d.success,
            delivered_at=d.delivered_at,
            error=d.error_message,
            created_at=d.created_at,
        )
        for d in records
    ]

    return PaginatedResponse(
        items=items,
        limit=max(len(items), 20),
        offset=0,
        count=len(items),
    )


# ---------------------------------------------------------------------------
# Remote triage mutations (acknowledge, resolve)
# ---------------------------------------------------------------------------


@router.post(
    "/{alert_id}/acknowledge",
    summary="Acknowledge alert",
    description="Transition an alert from OPEN to ACKNOWLEDGED.",
    response_model=AlertResponse,
    dependencies=[Depends(require_mutation_auth)],
)
async def acknowledge_alert(
    alert_id: int = Path(..., ge=1, description="Alert ID"),
    session: AsyncSession = Depends(get_session),
) -> AlertResponse:
    service = AlertTriageService(session)
    now = datetime.now(UTC)
    try:
        updated = await service.acknowledge(alert_id, at=now)
    except AlertNotFoundError:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="ALERT_NOT_FOUND",
            message=f"Alert {alert_id} not found.",
        ) from None
    except InvalidAlertStateTransitionError as exc:
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            code="INVALID_TRANSITION",
            message=str(exc),
        ) from None

    return AlertResponse(
        id=updated.id,
        alert_type=updated.alert_type.upper(),
        severity=updated.severity.upper(),
        status=updated.status.upper(),
        target=updated.host.address if updated.host else "",
        port=updated.port,
        message=updated.message,
        created_at=updated.created_at,
        acknowledged_at=updated.acknowledged_at,
        resolved_at=updated.resolved_at,
    )


@router.post(
    "/{alert_id}/resolve",
    summary="Resolve alert",
    description="Transition an alert from OPEN or ACKNOWLEDGED to RESOLVED.",
    response_model=AlertResponse,
    dependencies=[Depends(require_mutation_auth)],
)
async def resolve_alert(
    alert_id: int = Path(..., ge=1, description="Alert ID"),
    session: AsyncSession = Depends(get_session),
) -> AlertResponse:
    service = AlertTriageService(session)
    now = datetime.now(UTC)
    try:
        updated = await service.resolve(alert_id, at=now)
    except AlertNotFoundError:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="ALERT_NOT_FOUND",
            message=f"Alert {alert_id} not found.",
        ) from None
    except InvalidAlertStateTransitionError as exc:
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            code="INVALID_TRANSITION",
            message=str(exc),
        ) from None

    return AlertResponse(
        id=updated.id,
        alert_type=updated.alert_type.upper(),
        severity=updated.severity.upper(),
        status=updated.status.upper(),
        target=updated.host.address if updated.host else "",
        port=updated.port,
        message=updated.message,
        created_at=updated.created_at,
        acknowledged_at=updated.acknowledged_at,
        resolved_at=updated.resolved_at,
    )
