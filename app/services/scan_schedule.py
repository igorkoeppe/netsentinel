"""ScanScheduleService — manage periodic scans configured per host.

The service validates and stores schedule configuration. Running the scans is
the job of :class:`~app.services.scheduled_scan.ScheduledScanRunner`.

Conservative defaults (see ``claude.md``): every schedule has an explicit,
bounded port list and an interval no shorter than ``SCHEDULE_MIN_INTERVAL``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from app.core.config import settings
from app.monitoring.target import InvalidTargetError, NetworkTarget
from app.repositories.host import HostRepository
from app.repositories.scan_schedule import (
    ScanScheduleRepository,
    ScheduleAlreadyExistsError,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.scan_schedule import ScanSchedule

# Upper bound on ports per schedule: scheduled scans repeat forever, so they
# stay small and explicit. Large ranges belong to a one-off, supervised scan.
MAX_SCHEDULE_PORTS = 100
DEFAULT_SCHEDULE_INTERVAL = 300

_PORT_MIN = 1
_PORT_MAX = 65535

__all__ = [
    "DEFAULT_SCHEDULE_INTERVAL",
    "MAX_SCHEDULE_PORTS",
    "InvalidScheduleError",
    "ScanScheduleService",
    "ScheduleAlreadyExistsError",
    "ScheduleItem",
    "ScheduleNotFoundError",
    "normalize_schedule_ports",
]


class InvalidScheduleError(ValueError):
    """Raised when a schedule configuration is rejected."""


class ScheduleNotFoundError(Exception):
    """Raised when a schedule id does not exist."""

    def __init__(self, schedule_id: int) -> None:
        self.schedule_id = schedule_id
        super().__init__(f"Schedule {schedule_id} not found.")


@dataclass(frozen=True)
class ScheduleItem:
    """Read-only presentation item for a schedule."""

    id: int
    host_id: int
    address: str
    name: str | None
    ports: tuple[int, ...]
    interval_seconds: int
    enabled: bool
    next_run_at: datetime
    last_run_at: datetime | None
    last_scan_id: int | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime | None


def normalize_schedule_ports(ports: list[int]) -> list[int]:
    """Validate, deduplicate and sort a schedule's port list."""
    unique = sorted(set(ports))
    if not unique:
        raise InvalidScheduleError("A schedule needs at least one TCP port.")
    for port in unique:
        if isinstance(port, bool) or not _PORT_MIN <= port <= _PORT_MAX:
            raise InvalidScheduleError(
                f"Invalid TCP port {port}: must be between {_PORT_MIN} and {_PORT_MAX}."
            )
    if len(unique) > MAX_SCHEDULE_PORTS:
        raise InvalidScheduleError(
            f"A schedule accepts at most {MAX_SCHEDULE_PORTS} ports, got {len(unique)}."
        )
    return unique


def _to_item(schedule: ScanSchedule) -> ScheduleItem:
    return ScheduleItem(
        id=schedule.id,
        host_id=schedule.host_id,
        address=schedule.host.address,
        name=schedule.host.name,
        ports=tuple(schedule.ports),
        interval_seconds=schedule.interval_seconds,
        enabled=schedule.enabled,
        next_run_at=schedule.next_run_at,
        last_run_at=schedule.last_run_at,
        last_scan_id=schedule.last_scan_id,
        last_error=schedule.last_error,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at,
    )


class ScanScheduleService:
    """Create, update and query scan schedules.

    Mutations commit on success and roll back on failure, like the other
    write services (see :class:`~app.services.alert_triage.AlertTriageService`).
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        min_interval: int | None = None,
    ) -> None:
        self._session = session
        self._host_repo = HostRepository(session)
        self._schedule_repo = ScanScheduleRepository(session)
        self._min_interval = (
            min_interval if min_interval is not None else settings.SCHEDULE_MIN_INTERVAL
        )

    def _validate_interval(self, interval_seconds: int) -> int:
        if interval_seconds < self._min_interval:
            raise InvalidScheduleError(
                f"Interval must be at least {self._min_interval} seconds, "
                f"got {interval_seconds}."
            )
        return interval_seconds

    async def create_schedule(
        self,
        *,
        target: str,
        ports: list[int],
        interval_seconds: int,
        now: datetime,
        enabled: bool = True,
    ) -> ScheduleItem:
        """Register a periodic scan for ``target``; the first run is due now.

        The host is created if it is not known yet.

        Raises
        ------
        InvalidScheduleError
            Invalid target, ports or interval.
        ScheduleAlreadyExistsError
            The host already has a schedule.
        """
        try:
            parsed = NetworkTarget.parse(target)
        except InvalidTargetError as exc:
            raise InvalidScheduleError(f"Invalid target: {exc.reason}") from None
        normalized_ports = normalize_schedule_ports(ports)
        self._validate_interval(interval_seconds)

        try:
            host = await self._host_repo.get_or_create(address=parsed.value)
            schedule = await self._schedule_repo.create(
                host_id=host.id,
                ports=normalized_ports,
                interval_seconds=interval_seconds,
                next_run_at=now,
                enabled=enabled,
            )
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        return _to_item(schedule)

    async def update_schedule(
        self,
        schedule_id: int,
        *,
        now: datetime,
        ports: list[int] | None = None,
        interval_seconds: int | None = None,
        enabled: bool | None = None,
    ) -> ScheduleItem:
        """Change ports, interval and/or enabled state of a schedule.

        Re-enabling a schedule makes it due immediately. Shortening the
        interval brings ``next_run_at`` forward so the change takes effect
        without waiting for the old, longer interval.
        """
        normalized_ports = (
            normalize_schedule_ports(ports) if ports is not None else None
        )
        if interval_seconds is not None:
            self._validate_interval(interval_seconds)

        try:
            schedule = await self._schedule_repo.get_by_id(schedule_id)
            if schedule is None:
                raise ScheduleNotFoundError(schedule_id)

            next_run_at = schedule.next_run_at
            if enabled and not schedule.enabled:
                next_run_at = now
            elif interval_seconds is not None:
                next_run_at = min(
                    next_run_at, now + timedelta(seconds=interval_seconds)
                )

            schedule = await self._schedule_repo.update(
                schedule,
                ports=normalized_ports,
                interval_seconds=interval_seconds,
                enabled=enabled,
                next_run_at=next_run_at,
            )
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        return _to_item(schedule)

    async def get_schedule(self, schedule_id: int) -> ScheduleItem:
        """Return one schedule or raise :class:`ScheduleNotFoundError`."""
        schedule = await self._schedule_repo.get_by_id(schedule_id)
        if schedule is None:
            raise ScheduleNotFoundError(schedule_id)
        return _to_item(schedule)

    async def list_schedules(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        enabled: bool | None = None,
    ) -> list[ScheduleItem]:
        """Return schedules ordered by id."""
        if limit <= 0:
            raise ValueError(f"limit must be a positive integer, got {limit!r}")
        if offset < 0:
            raise ValueError(f"offset must be non-negative, got {offset!r}")
        records = await self._schedule_repo.list(
            enabled=enabled, limit=limit, offset=offset
        )
        return [_to_item(s) for s in records]
