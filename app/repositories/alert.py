"""AlertRepository — data access layer for SecurityAlertRecord."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.detection.alerts import SecurityAlert
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
            created_at=alert.timestamp,
        )
        self._session.add(record)
        await self._session.flush()
        await self._session.refresh(record)
        logger.debug(
            "SecurityAlertRecord created: id=%s host_id=%s severity=%r alert_type=%r",
            record.id,
            host_id,
            record.severity,
            record.alert_type,
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
        limit: int | None = None,
    ) -> list[SecurityAlertRecord]:
        """Return all alerts for a host, ordered most-recent first.

        Ordering: ``created_at DESC, id DESC``.
        """
        if limit is not None and limit <= 0:
            raise ValueError(f"limit must be a positive integer, got {limit!r}")

        stmt = (
            select(SecurityAlertRecord)
            .where(SecurityAlertRecord.host_id == host_id)
            .order_by(
                SecurityAlertRecord.created_at.desc(),
                SecurityAlertRecord.id.desc(),
            )
        )
        if limit is not None:
            stmt = stmt.limit(limit)

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
