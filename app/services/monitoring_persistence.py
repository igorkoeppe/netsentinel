"""Transactional persistence for monitoring cycles.

This service orchestrates the Host, Scan, and MonitoringEvent repositories
to persist a complete monitoring cycle (a snapshot and its resulting events)
atomically.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.repositories.host import HostRepository
from app.repositories.monitoring_event import MonitoringEventRepository
from app.repositories.scan import PortResultInput, ScanRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.detection.engine import MonitoringEvent
    from app.models.host import Host
    from app.models.monitoring_event import MonitoringEventRecord
    from app.models.scan import Scan
    from app.monitoring.monitor import MonitoringSnapshot

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PersistedMonitoringCycle:
    """The ORM records created or retrieved during a persistence cycle."""

    host: Host
    scan: Scan
    events: list[MonitoringEventRecord]


class MonitoringPersistenceService:
    """Service to persist monitoring cycles transactionally.

    Coordinates Host, Scan, and MonitoringEvent repositories.
    Guarantees atomic commit or rollback.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._host_repo = HostRepository(session)
        self._scan_repo = ScanRepository(session)
        self._event_repo = MonitoringEventRepository(session)

    async def persist_cycle(
        self,
        snapshot: MonitoringSnapshot,
        events: list[MonitoringEvent],
    ) -> PersistedMonitoringCycle:
        """Persist a complete monitoring cycle in a single transaction.

        Flow:
        1. Find the host by address. If it does not exist, create it.
        2. Create a scan record from the snapshot data.
        3. Persist all port results from the snapshot.
        4. Persist all monitoring events, tied to the host and the new scan.
        5. Commit the transaction.

        If any operation fails (e.g. database error, concurrent host creation),
        the entire transaction is rolled back and the exception is re-raised.

        Parameters
        ----------
        snapshot:
            The raw snapshot (HostAvailabilityResult) produced by the monitor.
        events:
            The list of state changes detected during this cycle. May be empty.

        Returns
        -------
        PersistedMonitoringCycle
            The resulting ORM records.

        Raises
        ------
        Exception
            Any database error encountered during the cycle. The session will
            be safely rolled back before the exception propagates.
        """
        address = snapshot.target.value

        try:
            # 1. Resolve Host
            host = await self._host_repo.get_by_address(address)
            if host is None:
                host = await self._host_repo.create(address=address)

            # 2. Create Scan
            scan = await self._scan_repo.create(
                host_id=host.id,
                status=snapshot.status.value,
                response_time_ms=snapshot.response_time_ms,
                started_at=snapshot.scan_result.started_at,
                finished_at=snapshot.scan_result.finished_at,
            )

            # 3. Create Port Results
            port_inputs = [
                PortResultInput(
                    port=pr.port,
                    status=pr.status.value,
                    response_time_ms=pr.duration_ms,
                )
                for pr in snapshot.scan_result.ports
            ]
            await self._scan_repo.add_port_results(
                scan_id=scan.id,
                results=port_inputs,
            )

            # 4. Create Monitoring Events
            records = await self._event_repo.create_many(
                host_id=host.id,
                scan_id=scan.id,
                events=events,
            )

            # 5. Commit atomic transaction
            await self._session.commit()

            logger.debug(
                "Persisted monitoring cycle for host=%s scan=%s events=%d",
                host.id,
                scan.id,
                len(records),
            )
            return PersistedMonitoringCycle(
                host=host,
                scan=scan,
                events=records,
            )

        except Exception as e:
            # Rollback safely on ANY error (including IntegrityError)
            logger.error("Failed to persist monitoring cycle, rolling back: %s", e)
            await self._session.rollback()
            raise
