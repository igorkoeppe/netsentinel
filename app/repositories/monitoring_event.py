"""MonitoringEventRepository — data access layer for MonitoringEventRecord.

Design decisions
----------------

Session injection
    ``MonitoringEventRepository`` receives an ``AsyncSession`` at construction
    time.  It never creates its own session.  The caller controls session
    lifetime and transaction boundaries.

Commit policy
    The repository executes ``add → flush`` (and ``refresh`` for ``create``)
    but **never commits**.  The caller decides when to call
    ``await session.commit()``.

    This allows future atomic writes spanning all persistence models::

        scan  = await scan_repo.create(...)
        await scan_repo.add_port_results(scan.id, port_inputs)
        await event_repo.create_many(host_id=host.id, scan_id=scan.id,
                                     events=events)
        await session.commit()  # all or nothing

Rollback policy
    After any ``IntegrityError`` the repository re-raises **without rolling
    back**.  The session is left in a broken state (PostgreSQL rejects further
    operations within the same transaction).  **The caller must rollback before
    reusing the session**::

        try:
            await repo.create(host_id=999, ...)
        except IntegrityError:
            await session.rollback()

    This is identical to the policy in ``HostRepository`` and
    ``ScanRepository``.

Mapping MonitoringEvent → MonitoringEventRecord
    The repository accepts the domain dataclass ``MonitoringEvent`` directly.
    This is appropriate because it is persisteing events that were already
    detected by the engine — accepting the domain type eliminates
    the need for a separate DTO.  Fields are mapped as follows:

    ========================  =============================================
    MonitoringEvent field     MonitoringEventRecord column
    ========================  =============================================
    event_type                event_type  (StrEnum → string value)
    timestamp                 created_at  (preserves original observation)
    port                      port        (None for host-level events)
    previous_state            previous_state
    current_state             current_state
    ========================  =============================================

    ``host_id`` and ``scan_id`` are supplied by the caller, not derived from
    the domain event, because the domain event carries a ``NetworkTarget``
    (address string) rather than a database primary key.

Timestamp preservation
    ``created_at`` uses ``server_default=func.now()`` in the ORM model, but
    SQLAlchemy only applies the server default when the column value is not set
    in the INSERT.  By explicitly setting ``created_at=event.timestamp`` the
    repository preserves the original observation time rather than the
    database commit time.

Ordering
    ``list_by_host`` returns events ordered ``created_at DESC, id DESC``
    (most-recent first; ``id DESC`` is a stable tiebreaker for events with
    identical timestamps).

    ``list_by_scan`` returns events ordered ``id ASC`` — the natural insertion
    order, which reflects the detection engine's deterministic output order
    (host events first, then port events sorted by port number).

Consistency limitation (host_id / scan_id)
    The schema has two independent FK constraints:
    ``monitoring_events.host_id → hosts.id`` and
    ``monitoring_events.scan_id → scans.id``.
    It is therefore possible to supply a ``scan_id`` that belongs to a
    different host than ``host_id``.  The database will not detect this
    inconsistency automatically.  The future ``PersistenceService`` (which
    owns the transaction) is responsible for ensuring that the scan belongs
    to the correct host before calling this repository.
"""

from __future__ import annotations

import logging
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.detection.engine import MonitoringEvent
from app.models.monitoring_event import MonitoringEventRecord

logger = logging.getLogger(__name__)


class MonitoringEventRepository:
    """Data access layer for
    :class:`~app.models.monitoring_event.MonitoringEventRecord`.

    All database operations for monitoring event history are centralised here.
    Application code must not write raw SQLAlchemy queries for events.

    Parameters
    ----------
    session:
        An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.  The repository
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
        event: MonitoringEvent,
    ) -> MonitoringEventRecord:
        """Persist a single monitoring event and return the record with id populated.

        The event's ``timestamp`` is stored in ``created_at``, preserving
        the original observation time.

        Parameters
        ----------
        host_id:
            Primary key of the host this event belongs to.
        scan_id:
            Primary key of the scan this event belongs to, or ``None``
            if the event is not associated with a specific scan.
        event:
            The domain :class:`~app.detection.engine.MonitoringEvent`
            to persist.

        Returns
        -------
        MonitoringEventRecord
            The newly created ORM instance with ``id`` and ``created_at``
            populated after flush.

        Raises
        ------
        sqlalchemy.exc.IntegrityError
            If ``host_id`` or ``scan_id`` does not reference a valid row.
            The session is **not** rolled back — the caller must do so.
        """
        record = MonitoringEventRecord(
            host_id=host_id,
            scan_id=scan_id,
            event_type=str(event.event_type),
            port=event.port,
            previous_state=event.previous_state,
            current_state=event.current_state,
            created_at=event.timestamp,
        )
        self._session.add(record)
        await self._session.flush()
        await self._session.refresh(record)
        logger.debug(
            "MonitoringEventRecord created: id=%s host_id=%s event_type=%r",
            record.id,
            host_id,
            record.event_type,
        )
        return record

    async def create_many(
        self,
        *,
        host_id: int,
        scan_id: int | None,
        events: list[MonitoringEvent],
    ) -> list[MonitoringEventRecord]:
        """Persist multiple monitoring events in a single flush.

        All ``MonitoringEventRecord`` rows are added to the session before a
        single ``flush()`` is issued, avoiding N round-trips for N events.

        If ``events`` is empty no database operation is performed and an empty
        list is returned immediately.

        Parameters
        ----------
        host_id:
            Primary key of the host these events belong to.
        scan_id:
            Primary key of the associated scan, or ``None``.
        events:
            Domain events to persist.  The list may be empty.

        Returns
        -------
        list[MonitoringEventRecord]
            The persisted ORM instances, in the same order as ``events``.

        Raises
        ------
        sqlalchemy.exc.IntegrityError
            If ``host_id`` or ``scan_id`` does not reference a valid row.
            The session is **not** rolled back — the caller must do so.
        """
        if not events:
            return []

        records = [
            MonitoringEventRecord(
                host_id=host_id,
                scan_id=scan_id,
                event_type=str(e.event_type),
                port=e.port,
                previous_state=e.previous_state,
                current_state=e.current_state,
                created_at=e.timestamp,
            )
            for e in events
        ]
        self._session.add_all(records)
        await self._session.flush()
        logger.debug(
            "MonitoringEventRecords created: host_id=%s count=%d",
            host_id,
            len(records),
        )
        return records

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_by_id(self, event_id: int) -> MonitoringEventRecord | None:
        """Return the event record with the given primary key, or ``None``.

        Parameters
        ----------
        event_id:
            Integer primary key.

        Returns
        -------
        MonitoringEventRecord | None
        """
        return cast(
            MonitoringEventRecord | None,
            await self._session.get(MonitoringEventRecord, event_id),
        )

    async def list_by_host(
        self,
        host_id: int,
        *,
        limit: int | None = None,
    ) -> list[MonitoringEventRecord]:
        """Return all events for a host, ordered most-recent first.

        Ordering: ``created_at DESC, id DESC``.  The secondary ``id DESC``
        sort provides a stable tiebreaker for events with identical timestamps
        (e.g. multiple events from the same scan cycle).

        Parameters
        ----------
        host_id:
            Primary key of the host.
        limit:
            Maximum number of records to return.  ``None`` returns all.
            Must be a positive integer when provided.

        Returns
        -------
        list[MonitoringEventRecord]

        Raises
        ------
        ValueError
            If ``limit`` is provided but is not a positive integer.
        """
        if limit is not None and limit <= 0:
            raise ValueError(f"limit must be a positive integer, got {limit!r}")

        stmt = (
            select(MonitoringEventRecord)
            .where(MonitoringEventRecord.host_id == host_id)
            .order_by(
                MonitoringEventRecord.created_at.desc(),
                MonitoringEventRecord.id.desc(),
            )
        )
        if limit is not None:
            stmt = stmt.limit(limit)

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_scan(self, scan_id: int) -> list[MonitoringEventRecord]:
        """Return all events for a specific scan, ordered by insertion order.

        Ordering: ``id ASC``.  This reflects the detection engine's output
        order — host events first, then port events sorted by port number —
        which is the natural order for replaying what happened during a cycle.

        Parameters
        ----------
        scan_id:
            Primary key of the scan.

        Returns
        -------
        list[MonitoringEventRecord]
        """
        stmt = (
            select(MonitoringEventRecord)
            .where(MonitoringEventRecord.scan_id == scan_id)
            .order_by(MonitoringEventRecord.id.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
