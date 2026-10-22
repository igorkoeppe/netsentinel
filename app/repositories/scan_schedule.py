"""ScanScheduleRepository — data access layer for the ScanSchedule ORM model.

Follows the same conventions as the other repositories: the session is
injected, the repository flushes but never commits, and an ``IntegrityError``
is translated into a domain exception without rolling back (the caller must
rollback before reusing the session).

Claiming due schedules
    ``claim_due`` selects due rows with ``FOR UPDATE SKIP LOCKED`` and moves
    their ``next_run_at`` forward inside the caller's transaction. Once the
    caller commits, the claim is visible to everyone; until then, concurrent
    schedulers (for example several API workers) skip the locked rows. A
    schedule therefore runs once per interval even when more than one
    scheduler polls the same database.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.scan_schedule import ScanSchedule

logger = logging.getLogger(__name__)


class ScheduleAlreadyExistsError(Exception):
    """Raised when creating a second schedule for the same host.

    The caller **must** rollback the session before reusing it.
    """

    def __init__(self, host_id: int) -> None:
        self.host_id = host_id
        super().__init__(f"Host id={host_id} already has a scan schedule.")


class ScanScheduleRepository:
    """Data access layer for :class:`~app.models.scan_schedule.ScanSchedule`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def create(
        self,
        *,
        host_id: int,
        ports: list[int],
        interval_seconds: int,
        next_run_at: datetime,
        enabled: bool = True,
    ) -> ScanSchedule:
        """Persist a new schedule and return it with its host loaded.

        Raises
        ------
        ScheduleAlreadyExistsError
            If the host already has a schedule. The session is **not** rolled
            back — the caller must do so.
        """
        schedule = ScanSchedule(
            host_id=host_id,
            ports=list(ports),
            interval_seconds=interval_seconds,
            next_run_at=next_run_at,
            enabled=enabled,
        )
        self._session.add(schedule)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            logger.debug("Duplicate schedule for host_id=%s", host_id)
            raise ScheduleAlreadyExistsError(host_id) from exc
        await self._session.refresh(schedule, attribute_names=["host", "created_at"])
        logger.debug("Schedule created: id=%s host_id=%s", schedule.id, host_id)
        return schedule

    async def update(
        self,
        schedule: ScanSchedule,
        *,
        ports: list[int] | None = None,
        interval_seconds: int | None = None,
        enabled: bool | None = None,
        next_run_at: datetime | None = None,
    ) -> ScanSchedule:
        """Update mutable configuration fields.

        None of these columns is nullable, so ``None`` means "unchanged".
        """
        if ports is not None:
            schedule.ports = list(ports)
        if interval_seconds is not None:
            schedule.interval_seconds = interval_seconds
        if enabled is not None:
            schedule.enabled = enabled
        if next_run_at is not None:
            schedule.next_run_at = next_run_at

        self._session.add(schedule)
        await self._session.flush()
        # Only the server-side timestamp is reloaded: a full refresh would
        # expire the already-loaded ``host`` relationship.
        await self._session.refresh(schedule, attribute_names=["updated_at"])
        return schedule

    async def record_run(
        self,
        schedule_id: int,
        *,
        ran_at: datetime,
        scan_id: int | None,
        error: str | None,
    ) -> None:
        """Store the outcome of the latest run. Missing schedules are ignored.

        ``last_scan_id`` keeps pointing at the last successful scan when a run
        fails (``scan_id=None``); ``last_error`` is cleared by a success.
        """
        schedule = await self._session.get(ScanSchedule, schedule_id)
        if schedule is None:
            return
        schedule.last_run_at = ran_at
        if scan_id is not None:
            schedule.last_scan_id = scan_id
        schedule.last_error = error
        await self._session.flush()

    async def claim_due(self, now: datetime, *, limit: int) -> list[ScanSchedule]:
        """Lock due schedules and push their ``next_run_at`` one interval ahead.

        Returns the claimed schedules (with ``host`` loaded), ordered by how
        overdue they are. The caller must commit to release the row locks.
        """
        if limit <= 0:
            raise ValueError(f"limit must be a positive integer, got {limit!r}")

        stmt = (
            select(ScanSchedule)
            .where(ScanSchedule.enabled.is_(True), ScanSchedule.next_run_at <= now)
            .order_by(ScanSchedule.next_run_at, ScanSchedule.id)
            .limit(limit)
            .with_for_update(skip_locked=True, of=ScanSchedule)
            .options(selectinload(ScanSchedule.host))
        )
        schedules = list((await self._session.scalars(stmt)).all())
        for schedule in schedules:
            schedule.next_run_at = now + timedelta(seconds=schedule.interval_seconds)
        if schedules:
            await self._session.flush()
        return schedules

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_by_id(self, schedule_id: int) -> ScanSchedule | None:
        """Return the schedule (with its host) or ``None``."""
        stmt = (
            select(ScanSchedule)
            .where(ScanSchedule.id == schedule_id)
            .options(selectinload(ScanSchedule.host))
        )
        return cast(ScanSchedule | None, await self._session.scalar(stmt))

    async def get_by_host_id(self, host_id: int) -> ScanSchedule | None:
        """Return the schedule of a host (with its host) or ``None``."""
        stmt = (
            select(ScanSchedule)
            .where(ScanSchedule.host_id == host_id)
            .options(selectinload(ScanSchedule.host))
        )
        return cast(ScanSchedule | None, await self._session.scalar(stmt))

    async def list(
        self,
        *,
        enabled: bool | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ScanSchedule]:
        """Return schedules ordered by ``id`` with their hosts loaded."""
        stmt = (
            select(ScanSchedule)
            .options(selectinload(ScanSchedule.host))
            .order_by(ScanSchedule.id)
        )
        if enabled is not None:
            stmt = stmt.where(ScanSchedule.enabled.is_(enabled))
        if offset > 0:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list((await self._session.scalars(stmt)).all())
