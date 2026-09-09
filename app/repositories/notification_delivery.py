"""NotificationDeliveryRepository — data access layer for NotificationDeliveryRecord."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_delivery import NotificationDeliveryRecord

if TYPE_CHECKING:
    from app.notifications.models import DeliveryResult

logger = logging.getLogger(__name__)


class NotificationDeliveryRepository:
    """Data access layer for
    :class:`~app.models.notification_delivery.NotificationDeliveryRecord`.

    All database operations for notification delivery history are centralised here.

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
        alert_id: int,
        channel: str,
        notification_id: str,
        success: bool,
        delivered_at: datetime | None = None,
        error_message: str | None = None,
        created_at: datetime | None = None,
    ) -> NotificationDeliveryRecord:
        """Persist a single notification delivery record.

        Parameters
        ----------
        alert_id:
            Primary key of the associated security alert.
        channel:
            Channel name string (e.g. "webhook").
        notification_id:
            Unique identifier of the notification.
        success:
            Whether the delivery was successful.
        delivered_at:
            Timestamp when delivery completed, or None on failure.
        error_message:
            Error message if delivery failed, or None on success.
        created_at:
            Optional explicit creation timestamp (defaults to current UTC time).

        Returns
        -------
        NotificationDeliveryRecord
            The newly created and flushed ORM instance.
        """
        record = NotificationDeliveryRecord(
            alert_id=alert_id,
            channel=channel,
            notification_id=notification_id,
            success=success,
            delivered_at=delivered_at,
            error_message=error_message,
            created_at=created_at or datetime.now(UTC),
        )
        self._session.add(record)
        await self._session.flush()
        await self._session.refresh(record)
        logger.debug(
            "NotificationDeliveryRecord created: id=%s alert_id=%s "
            "channel=%r success=%s",
            record.id,
            alert_id,
            record.channel,
            record.success,
        )
        return record

    async def create_from_result(
        self,
        *,
        alert_id: int,
        result: DeliveryResult,
    ) -> NotificationDeliveryRecord:
        """Create and persist a delivery record directly from a domain DeliveryResult.

        Parameters
        ----------
        alert_id:
            Primary key of the associated security alert.
        result:
            The DeliveryResult (NotificationResult) to persist.

        Returns
        -------
        NotificationDeliveryRecord
            The newly created and flushed ORM instance.
        """
        channel_str = (
            result.channel.value
            if hasattr(result.channel, "value")
            else str(result.channel)
        )
        return await self.create(
            alert_id=alert_id,
            channel=channel_str,
            notification_id=result.notification_id,
            success=result.success,
            delivered_at=result.delivered_at,
            error_message=result.error_message,
        )

    async def create_many_from_results(
        self,
        items: Sequence[tuple[int, DeliveryResult]],
    ) -> list[NotificationDeliveryRecord]:
        """Persist multiple delivery results in a single flush.

        Parameters
        ----------
        items:
            Sequence of tuples (alert_id, DeliveryResult).

        Returns
        -------
        list[NotificationDeliveryRecord]
            The persisted ORM instances.
        """
        if not items:
            return []

        records = [
            NotificationDeliveryRecord(
                alert_id=alert_id,
                channel=(
                    res.channel.value
                    if hasattr(res.channel, "value")
                    else str(res.channel)
                ),
                notification_id=res.notification_id,
                success=res.success,
                delivered_at=res.delivered_at,
                error_message=res.error_message,
                created_at=datetime.now(UTC),
            )
            for alert_id, res in items
        ]
        self._session.add_all(records)
        await self._session.flush()
        logger.debug(
            "NotificationDeliveryRecords created: count=%d",
            len(records),
        )
        return records

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_by_id(self, delivery_id: int) -> NotificationDeliveryRecord | None:
        """Return the delivery record with the given primary key, or None."""
        return cast(
            NotificationDeliveryRecord | None,
            await self._session.get(NotificationDeliveryRecord, delivery_id),
        )

    async def list_by_alert(
        self,
        alert_id: int,
    ) -> list[NotificationDeliveryRecord]:
        """Return all delivery records for a specific alert, newest first."""
        stmt = (
            select(NotificationDeliveryRecord)
            .where(NotificationDeliveryRecord.alert_id == alert_id)
            .order_by(
                NotificationDeliveryRecord.created_at.desc(),
                NotificationDeliveryRecord.id.desc(),
            )
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_recent(
        self,
        *,
        limit: int = 20,
    ) -> list[NotificationDeliveryRecord]:
        """Return the most recent delivery records, newest first."""
        if limit <= 0:
            raise ValueError(f"limit must be a positive integer, got {limit!r}")

        stmt = (
            select(NotificationDeliveryRecord)
            .order_by(
                NotificationDeliveryRecord.created_at.desc(),
                NotificationDeliveryRecord.id.desc(),
            )
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_alerts(
        self,
        alert_ids: Sequence[int],
    ) -> dict[int, int]:
        """Count delivery records grouped by alert_id for a list of alert IDs."""
        if not alert_ids:
            return {}

        stmt = (
            select(
                NotificationDeliveryRecord.alert_id,
                func.count(NotificationDeliveryRecord.id).label("count"),
            )
            .where(NotificationDeliveryRecord.alert_id.in_(alert_ids))
            .group_by(NotificationDeliveryRecord.alert_id)
        )
        result = await self._session.execute(stmt)
        counts = {aid: 0 for aid in alert_ids}
        for row in result.all():
            if row[0] is not None:
                counts[row[0]] = row[1]
        return counts
