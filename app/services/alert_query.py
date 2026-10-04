"""AlertQueryService — read-only service for querying persisted security alerts.

Provides decoupled, read-only data transfer objects (DTOs) for alert queues
and historical inspection without exposing SQLAlchemy sessions or ORM models.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.detection.alerts import AlertStatus, AlertType, Severity
from app.repositories.alert import AlertRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlertListItem:
    """Read-only presentation item for a security alert.

    Attributes:
        id: Primary key of the alert record.
        severity: Defensive severity level string (e.g. "high", "medium").
        alert_type: Alert classification string (e.g. "unexpected_open_port").
        status: Lifecycle triage status string (e.g. "OPEN", "ACKNOWLEDGED",
            "RESOLVED").
        target: Network address or hostname of the associated target.
        port: Associated TCP port number, or None for host-level alerts.
        created_at: Timestamp when the alert was created.
        acknowledged_at: Timestamp when the alert was acknowledged, if applicable.
        resolved_at: Timestamp when the alert was resolved, if applicable.
    """

    id: int
    severity: str
    alert_type: str
    status: str
    target: str
    port: int | None
    created_at: datetime
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None


class AlertQueryService:
    """Internal read-only service for querying persisted security alerts.

    Parameters
    ----------
    session:
        An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
    alert_repo:
        Optional :class:`~app.repositories.alert.AlertRepository` instance.
        If omitted, one will be instantiated with ``session``.
    """

    def __init__(
        self,
        session: AsyncSession,
        alert_repo: AlertRepository | None = None,
    ) -> None:
        self._session = session
        self._alert_repo = alert_repo or AlertRepository(session)

    async def list_alerts(
        self,
        limit: int = 20,
        status: AlertStatus | None = None,
        severity: Severity | None = None,
        alert_type: AlertType | None = None,
        target: str | None = None,
        offset: int = 0,
    ) -> list[AlertListItem]:
        """Fetch the most recent persisted security alerts globally.

        Parameters
        ----------
        limit:
            Maximum number of alerts to return. Must be a positive integer.
        status:
            Optional lifecycle status filter.
        severity:
            Optional severity level filter.
        alert_type:
            Optional alert type classification filter.
        target:
            Optional target network address filter.
        offset:
            Optional pagination offset (default 0).

        Returns
        -------
        list[AlertListItem]
            List of alert DTOs ordered newest first matching the filters.

        Raises
        ------
        ValueError
            If ``limit <= 0`` or ``offset < 0``.
        TypeError
            If ``status``, ``severity``, ``alert_type``, or ``target``
            have invalid types.
        """
        if limit <= 0:
            raise ValueError(f"limit must be a positive integer, got {limit!r}")
        if offset < 0:
            raise ValueError(f"offset must be non-negative, got {offset!r}")
        if status is not None and not isinstance(status, AlertStatus):
            raise TypeError(
                f"status must be an AlertStatus, got {type(status).__name__}"
            )
        if severity is not None and not isinstance(severity, Severity):
            raise TypeError(
                f"severity must be a Severity, got {type(severity).__name__}"
            )
        if alert_type is not None and not isinstance(alert_type, AlertType):
            raise TypeError(
                f"alert_type must be an AlertType, got {type(alert_type).__name__}"
            )
        if target is not None and not isinstance(target, str):
            raise TypeError(f"target must be a str, got {type(target).__name__}")

        if alert_type is None and target is None and offset == 0:
            records = await self._alert_repo.list_recent(
                limit=limit,
                status=status,
                severity=severity,
            )
        else:
            records = await self._alert_repo.list_recent(
                limit=limit,
                status=status,
                severity=severity,
                alert_type=alert_type,
                target=target,
                offset=offset,
            )

        return [
            AlertListItem(
                id=rec.id,
                severity=rec.severity,
                alert_type=rec.alert_type,
                status=rec.status,
                target=rec.host.address if rec.host is not None else "",
                port=rec.port,
                created_at=rec.created_at,
                acknowledged_at=rec.acknowledged_at,
                resolved_at=rec.resolved_at,
            )
            for rec in records
        ]

    async def get_summary(self) -> dict[str, Any]:
        """Aggregate counts of persisted alerts by status and severity."""
        return await self._alert_repo.get_summary()

    async def get_alert(self, alert_id: int) -> AlertListItem | None:
        """Fetch a single security alert by its ID.

        Parameters
        ----------
        alert_id:
            Primary key of the alert.

        Returns
        -------
        AlertListItem | None
            The alert DTO, or None if not found.
        """
        rec = await self._alert_repo.get_by_id(alert_id)
        if rec is None:
            return None

        return AlertListItem(
            id=rec.id,
            severity=rec.severity,
            alert_type=rec.alert_type,
            status=rec.status,
            target=rec.host.address if rec.host is not None else "",
            port=rec.port,
            created_at=rec.created_at,
            acknowledged_at=rec.acknowledged_at,
            resolved_at=rec.resolved_at,
        )
