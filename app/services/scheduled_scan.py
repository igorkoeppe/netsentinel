"""ScheduledScanRunner — execute due scan schedules.

One run of a schedule follows the same pipeline as ``netsentinel monitor
--persist``::

    scan (monitoring) → detect_changes (detection) → generate_alerts (rules)
        → MonitoringPersistenceService → NotificationDeliveryService

The only difference is the baseline. A long-running monitor keeps the previous
snapshot in memory; a scheduled run starts fresh every time, so the baseline is
rebuilt from the host's latest persisted scan. This also means the baseline
survives process restarts.

Every schedule is isolated: an unreachable target, an invalid stored address or
a database error is logged and recorded in ``scan_schedules.last_error`` without
stopping the other schedules in the batch.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.detection.engine import detect_changes
from app.detection.rules import DEFAULT_ALERT_POLICY, AlertPolicy, generate_alerts
from app.monitoring.availability import (
    HostAvailabilityResult,
    HostStatus,
    check_host_availability,
)
from app.monitoring.port_scanner import PortScanResult
from app.monitoring.scheduler import Scheduler
from app.monitoring.target import InvalidTargetError, NetworkTarget
from app.monitoring.tcp_probe import PortStatus, TcpProbeResult
from app.repositories.host import HostRepository
from app.repositories.scan import ScanRepository
from app.repositories.scan_schedule import ScanScheduleRepository
from app.services.monitoring_persistence import MonitoringPersistenceService
from app.services.notification_delivery import NotificationDeliveryService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.detection.alerts import SecurityAlert
    from app.models.scan import Scan
    from app.notifications.policy import NotificationPolicy
    from app.notifications.sender import NotificationSender

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager["AsyncSession"]]
ScanFunction = Callable[[NetworkTarget, list[int]], Awaitable[HostAvailabilityResult]]

# Stored error messages are for operators, not stack traces.
_MAX_ERROR_LENGTH = 500


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def _default_scan(
    target: NetworkTarget, ports: list[int]
) -> HostAvailabilityResult:
    return await check_host_availability(target=target, ports=ports)


@dataclass(frozen=True)
class ScheduledRunResult:
    """Outcome of one scheduled run."""

    schedule_id: int
    address: str
    scan_id: int | None = None
    event_count: int = 0
    alerts: list[SecurityAlert] = field(default_factory=list)
    error: str | None = None


def snapshot_from_scan(
    scan: Scan, target: NetworkTarget
) -> HostAvailabilityResult | None:
    """Rebuild a detection snapshot from a persisted scan.

    Returns ``None`` when the stored values are not recognised (for example a
    status written by a future version), so the run proceeds without a
    baseline instead of producing misleading alerts.
    """
    try:
        status = HostStatus(scan.status)
        probes = tuple(
            TcpProbeResult(
                target=target,
                port=pr.port,
                status=PortStatus(pr.status),
                duration_ms=pr.response_time_ms or 0.0,
            )
            for pr in scan.port_results
        )
    except ValueError:
        logger.warning("Scan %s has unknown status values; no baseline", scan.id)
        return None

    finished_at = scan.finished_at or scan.started_at
    return HostAvailabilityResult(
        target=target,
        status=status,
        response_time_ms=scan.response_time_ms or 0.0,
        scan_result=PortScanResult(
            target=target,
            started_at=scan.started_at,
            finished_at=finished_at,
            duration_ms=(finished_at - scan.started_at).total_seconds() * 1000,
            ports=probes,
        ),
    )


def _short_error(exc: BaseException) -> str:
    message = f"{type(exc).__name__}: {exc}"
    return message[:_MAX_ERROR_LENGTH]


class ScheduledScanRunner:
    """Claim due schedules and run them one after another.

    Parameters
    ----------
    session_factory:
        Returns an async context manager yielding a fresh ``AsyncSession``
        (normally :func:`app.db.session.get_db_session`). Each step opens its
        own session so a failure never leaves a broken transaction behind.
    policy:
        Alert severities, shared with ``netsentinel monitor``.
    scan:
        Function that scans a target. Injected so tests never touch the
        network.
    notification_policy, sender:
        Optional notification delivery, enabled only when both are given.
    batch_size:
        Maximum schedules claimed per :meth:`run_due` call.
    clock:
        Source of the timestamp recorded for failed runs.
    """

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        policy: AlertPolicy = DEFAULT_ALERT_POLICY,
        scan: ScanFunction = _default_scan,
        notification_policy: NotificationPolicy | None = None,
        sender: NotificationSender | None = None,
        batch_size: int = 10,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        if batch_size <= 0:
            raise ValueError(f"batch_size must be positive, got {batch_size!r}")
        self._session_factory = session_factory
        self._policy = policy
        self._scan = scan
        self._notification_policy = notification_policy
        self._sender = sender
        self._batch_size = batch_size
        self._clock = clock

    async def run_due(self, now: datetime) -> list[ScheduledRunResult]:
        """Run every schedule due at ``now`` (up to ``batch_size``)."""
        async with self._session_factory() as session:
            try:
                claimed = await ScanScheduleRepository(session).claim_due(
                    now, limit=self._batch_size
                )
                jobs = [(s.id, s.host.address, list(s.ports)) for s in claimed]
                await session.commit()
            except Exception:
                await session.rollback()
                raise

        if jobs:
            logger.info("Running %d scheduled scan(s)", len(jobs))
        return [await self.run_one(*job) for job in jobs]

    async def run_one(
        self, schedule_id: int, address: str, ports: list[int]
    ) -> ScheduledRunResult:
        """Scan one target, detect changes against its last scan and persist."""
        try:
            target = NetworkTarget.parse(address)
            snapshot = await self._scan(target, ports)
        except InvalidTargetError as exc:
            return await self._fail(schedule_id, address, f"Invalid target: {exc}")
        except Exception as exc:
            logger.warning("Scheduled scan %s failed: %s", schedule_id, exc)
            return await self._fail(schedule_id, address, _short_error(exc))

        try:
            return await self._persist(schedule_id, target, snapshot)
        except Exception as exc:
            logger.exception("Could not persist scheduled scan %s", schedule_id)
            return await self._fail(schedule_id, address, _short_error(exc))

    async def _persist(
        self,
        schedule_id: int,
        target: NetworkTarget,
        snapshot: HostAvailabilityResult,
    ) -> ScheduledRunResult:
        async with self._session_factory() as session:
            baseline = await self._load_baseline(session, target)
            events = detect_changes(baseline, snapshot)
            alerts = generate_alerts(events, policy=self._policy)

            # persist_cycle commits (or rolls back) the scan, events and alerts.
            cycle = await MonitoringPersistenceService(session).persist_cycle(
                snapshot, events, alerts
            )
            await ScanScheduleRepository(session).record_run(
                schedule_id,
                ran_at=snapshot.scan_result.started_at,
                scan_id=cycle.scan.id,
                error=None,
            )
            await session.commit()

            if alerts and self._sender is not None and self._notification_policy:
                # The scan is already committed: a delivery problem must not
                # mark the run as failed.
                try:
                    await NotificationDeliveryService(
                        session=session,
                        policy=self._notification_policy,
                        sender=self._sender,
                    ).deliver_alerts(alerts=alerts, alert_records=cycle.alerts)
                except Exception:
                    logger.exception(
                        "Notification delivery failed for schedule %s", schedule_id
                    )

        return ScheduledRunResult(
            schedule_id=schedule_id,
            address=target.value,
            scan_id=cycle.scan.id,
            event_count=len(events),
            alerts=alerts,
        )

    @staticmethod
    async def _load_baseline(
        session: AsyncSession, target: NetworkTarget
    ) -> HostAvailabilityResult | None:
        host = await HostRepository(session).get_by_address(target.value)
        if host is None:
            return None
        latest = await ScanRepository(session).get_latest_for_host(host.id)
        if latest is None:
            return None
        return snapshot_from_scan(latest, target)

    async def _fail(
        self, schedule_id: int, address: str, error: str
    ) -> ScheduledRunResult:
        """Record a failed run. A failure to record is logged, never raised."""
        try:
            async with self._session_factory() as session:
                await ScanScheduleRepository(session).record_run(
                    schedule_id,
                    ran_at=self._clock(),
                    scan_id=None,
                    error=error,
                )
                await session.commit()
        except Exception:
            logger.exception("Could not record failure of schedule %s", schedule_id)
        return ScheduledRunResult(schedule_id=schedule_id, address=address, error=error)


def create_scheduled_scan_runner(
    session_factory: SessionFactory | None = None,
) -> ScheduledScanRunner:
    """Build a runner from settings (alert policy, webhook, batch size).

    Invalid alert or notification settings raise ``ValueError`` here, at
    startup, rather than on the first scheduled run.
    """
    from app.core.config import settings

    if session_factory is None:
        from app.db.session import get_db_session

        session_factory = get_db_session

    sender = settings.get_webhook_sender()
    return ScheduledScanRunner(
        session_factory,
        policy=settings.get_alert_policy(),
        notification_policy=(
            settings.get_notification_policy() if sender is not None else None
        ),
        sender=sender,
        batch_size=settings.SCHEDULER_BATCH_SIZE,
    )


def create_scan_scheduler(session_factory: SessionFactory | None = None) -> Scheduler:
    """Build the in-process scheduler used by the API lifespan."""
    from app.core.config import settings

    runner = create_scheduled_scan_runner(session_factory)
    return Scheduler(runner.run_due, poll_interval=settings.SCHEDULER_POLL_INTERVAL)
