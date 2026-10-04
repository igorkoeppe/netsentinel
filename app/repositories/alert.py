"""AlertRepository — data access layer for SecurityAlertRecord."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.detection.alerts import (
    AlertLifecycle,
    AlertStatus,
    AlertType,
    SecurityAlert,
    Severity,
)
from app.models.host import Host
from app.models.security_alert import SecurityAlertRecord

logger = logging.getLogger(__name__)


class AlertRepository:
    """Data access layer for :class:`~app.models.security_alert.SecurityAlertRecord`.

    All database operations for security alert history are centralised here.

    Parameters
    ----------
    session:
        An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`. The repository
        borrows the session — it does **not** close, commit, or rollback it.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def create(
        self,
        *,
        host_id: int,
        scan_id: int | None,
        monitoring_event_id: int | None,
        alert: SecurityAlert,
    ) -> SecurityAlertRecord:
        """Persist a single security alert and return the record with id populated.

        Parameters
        ----------
        host_id:
            Primary key of the host this alert belongs to.
        scan_id:
            Primary key of the scan this alert belongs to, or ``None``.
        monitoring_event_id:
            Primary key of the monitoring event this alert derives from, or ``None``.
        alert:
            The domain :class:`~app.detection.alerts.SecurityAlert` to persist.

        Returns
        -------
        SecurityAlertRecord
            The newly created ORM instance with ``id`` and ``created_at``
            populated after flush.
        """
        record = SecurityAlertRecord(
            host_id=host_id,
            scan_id=scan_id,
            monitoring_event_id=monitoring_event_id,
            alert_type=str(alert.alert_type),
            severity=str(alert.severity),
            message=alert.message,
            port=alert.port,
            status=str(alert.status),
            acknowledged_at=alert.acknowledged_at,
            resolved_at=alert.resolved_at,
            created_at=alert.timestamp,
        )
        self._session.add(record)
        await self._session.flush()
        await self._session.refresh(record)
        logger.debug(
            "SecurityAlertRecord created: id=%s host_id=%s severity=%r "
            "alert_type=%r status=%r",
            record.id,
            host_id,
            record.severity,
            record.alert_type,
            record.status,
        )
        return record

    async def create_many(
        self,
        *,
        host_id: int,
        scan_id: int | None,
        alerts: list[tuple[SecurityAlert, int | None]],
    ) -> list[SecurityAlertRecord]:
        """Persist multiple security alerts in a single flush.

        Parameters
        ----------
        host_id:
            Primary key of the host these alerts belong to.
        scan_id:
            Primary key of the associated scan, or ``None``.
        alerts:
            A list of tuples ``(SecurityAlert, monitoring_event_id)``.
            The list may be empty.

        Returns
        -------
        list[SecurityAlertRecord]
            The persisted ORM instances, in the same order as ``alerts``.
        """
        if not alerts:
            return []

        records = [
            SecurityAlertRecord(
                host_id=host_id,
                scan_id=scan_id,
                monitoring_event_id=event_id,
                alert_type=str(alert.alert_type),
                severity=str(alert.severity),
                message=alert.message,
                port=alert.port,
                status=str(alert.status),
                acknowledged_at=alert.acknowledged_at,
                resolved_at=alert.resolved_at,
                created_at=alert.timestamp,
            )
            for alert, event_id in alerts
        ]
        self._session.add_all(records)
        await self._session.flush()
        logger.debug(
            "SecurityAlertRecords created: host_id=%s count=%d",
            host_id,
            len(records),
        )
        return records

    async def update_lifecycle(
        self,
        alert_id: int,
        lifecycle: AlertLifecycle,
    ) -> SecurityAlertRecord | None:
        """Update the triage lifecycle state of an existing security alert.

        Parameters
        ----------
        alert_id:
            Primary key of the alert record to update.
        lifecycle:
            The validated domain :class:`~app.detection.alerts.AlertLifecycle`
            containing the new status and timestamps.

        Returns
        -------
        SecurityAlertRecord | None
            The updated record, or ``None`` if no record with ``alert_id`` exists.
        """
        record = await self._session.get(SecurityAlertRecord, alert_id)
        if record is None:
            return None

        record.status = str(lifecycle.status)
        record.acknowledged_at = lifecycle.acknowledged_at
        record.resolved_at = lifecycle.resolved_at

        await self._session.flush()
        await self._session.refresh(record)
        logger.debug(
            "SecurityAlertRecord lifecycle updated: id=%s status=%s",
            alert_id,
            record.status,
        )
        return record

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_by_id(self, alert_id: int) -> SecurityAlertRecord | None:
        """Return the alert record with the given primary key, or ``None``."""
        return cast(
            SecurityAlertRecord | None,
            await self._session.get(SecurityAlertRecord, alert_id),
        )

    async def list_by_host(
        self,
        host_id: int,
        *,
        limit: int = 50,
    ) -> list[SecurityAlertRecord]:
        """Return alerts for a given host, ordered newest first."""
        stmt = (
            select(SecurityAlertRecord)
            .where(SecurityAlertRecord.host_id == host_id)
            .order_by(
                SecurityAlertRecord.created_at.desc(),
                SecurityAlertRecord.id.desc(),
            )
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_scan(self, scan_id: int) -> list[SecurityAlertRecord]:
        """Return all alerts for a specific scan, ordered by created_at ASC, id ASC."""
        stmt = (
            select(SecurityAlertRecord)
            .where(SecurityAlertRecord.scan_id == scan_id)
            .order_by(
                SecurityAlertRecord.created_at.asc(),
                SecurityAlertRecord.id.asc(),
            )
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_scans(self, scan_ids: Sequence[int]) -> dict[int, int]:
        """Count alerts grouped by scan_id for a list of scan IDs in a single query."""
        if not scan_ids:
            return {}

        stmt = (
            select(
                SecurityAlertRecord.scan_id,
                func.count(SecurityAlertRecord.id).label("count"),
            )
            .where(SecurityAlertRecord.scan_id.in_(scan_ids))
            .group_by(SecurityAlertRecord.scan_id)
        )
        result = await self._session.execute(stmt)
        counts = {sid: 0 for sid in scan_ids}
        for row in result.all():
            if row[0] is not None:
                counts[row[0]] = row[1]
        return counts

    async def list_recent(
        self,
        *,
        limit: int = 20,
        status: AlertStatus | None = None,
        severity: Severity | None = None,
        alert_type: AlertType | None = None,
        target: str | None = None,
        offset: int = 0,
    ) -> list[SecurityAlertRecord]:
        """Return the most recent alerts globally, ordered created_at DESC, id DESC.

        The associated ``Host`` is eagerly loaded via ``joinedload`` to avoid N+1
        queries.

        Parameters
        ----------
        limit:
            Maximum number of alerts to return. Must be a positive integer.
        status:
            Optional lifecycle status filter.
        severity:
            Optional severity level filter.
        alert_type:
            Optional alert type filter.
        target:
            Optional target network address filter.
        offset:
            Optional offset for pagination (default 0).

        Returns
        -------
        list[SecurityAlertRecord]
            The alerts ordered newest first matching the specified filters.
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

        stmt = select(SecurityAlertRecord).options(joinedload(SecurityAlertRecord.host))
        if target is not None:
            stmt = stmt.join(SecurityAlertRecord.host).where(Host.address == target)
        if status is not None:
            stmt = stmt.where(SecurityAlertRecord.status == status.value)
        if severity is not None:
            stmt = stmt.where(SecurityAlertRecord.severity == severity.value)
        if alert_type is not None:
            stmt = stmt.where(SecurityAlertRecord.alert_type == alert_type.value)

        stmt = (
            stmt.order_by(
                SecurityAlertRecord.created_at.desc(),
                SecurityAlertRecord.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_summary(self) -> dict[str, Any]:
        """Aggregate alert counts by status and severity using SQL GROUP BY.

        Executes database aggregations without loading alert records into Python memory.
        Returns a dictionary containing total count and complete dictionaries for all
        known enum values (with 0 for unrepresented categories).
        """
        # Count total
        total_stmt = select(func.count(SecurityAlertRecord.id))
        total = await self._session.scalar(total_stmt) or 0

        # Group by status
        status_stmt = select(
            SecurityAlertRecord.status,
            func.count(SecurityAlertRecord.id),
        ).group_by(SecurityAlertRecord.status)
        status_rows = (await self._session.execute(status_stmt)).all()
        by_status = {s.value: 0 for s in AlertStatus}
        for st_val, cnt in status_rows:
            norm_st = str(st_val).upper()
            by_status[norm_st] = cnt

        # Group by severity (standardize keys to uppercase)
        sev_stmt = select(
            SecurityAlertRecord.severity,
            func.count(SecurityAlertRecord.id),
        ).group_by(SecurityAlertRecord.severity)
        sev_rows = (await self._session.execute(sev_stmt)).all()
        by_severity = {s.name: 0 for s in Severity}
        for sv_val, cnt in sev_rows:
            norm_sv = str(sv_val).upper()
            by_severity[norm_sv] = cnt

        return {
            "total": total,
            "by_status": by_status,
            "by_severity": by_severity,
        }
