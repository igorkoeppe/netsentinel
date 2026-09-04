import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.alert import AlertRepository
from app.repositories.host import HostRepository
from app.repositories.monitoring_event import MonitoringEventRepository
from app.repositories.scan import ScanRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EventSummary:
    event_type: str
    port: int | None
    previous_state: str | None
    current_state: str | None
    created_at: datetime


@dataclass(frozen=True)
class AlertSummary:
    id: int
    alert_type: str
    severity: str
    message: str
    port: int | None
    created_at: datetime
    monitoring_event_id: int | None


@dataclass(frozen=True)
class PortResultSummary:
    port: int
    status: str
    response_time_ms: float | None


@dataclass(frozen=True)
class ScanDetailsResult:
    scan_id: int
    status: str
    response_time_ms: float | None
    started_at: datetime
    finished_at: datetime | None
    ports: list[PortResultSummary]
    events: list[EventSummary]
    alerts: list[AlertSummary] = field(default_factory=list)


@dataclass(frozen=True)
class ScanHistorySummary:
    scan_id: int
    timestamp: datetime
    status: str
    response_time_ms: float | None
    port_count: int | None
    event_count: int | None
    alert_count: int | None = None


@dataclass(frozen=True)
class HostHistoryResult:
    host_id: int
    address: str
    name: str | None
    enabled: bool
    scans: list[ScanHistorySummary]


class HistoryService:
    """Internal service for reading historical monitoring data.

    This service coordinates queries across multiple repositories and returns
    simple data transfer objects (DTOs) detached from the ORM.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._host_repo = HostRepository(session)
        self._scan_repo = ScanRepository(session)
        self._event_repo = MonitoringEventRepository(session)
        self._alert_repo = AlertRepository(session)

    async def get_host_history(
        self, address: str, limit: int = 20
    ) -> HostHistoryResult | None:
        """Fetch the history of a host by its network address.

        Parameters
        ----------
        address:
            The network address of the host.
        limit:
            Maximum number of recent scans to return. Must be positive.

        Returns
        -------
        HostHistoryResult | None
            The history of the host, or None if the host does not exist.
        """
        if limit <= 0:
            raise ValueError(f"limit must be a positive integer, got {limit!r}")

        host = await self._host_repo.get_by_address(address)
        if host is None:
            return None

        scans = await self._scan_repo.list_by_host(host.id, limit=limit)
        scan_ids = [s.id for s in scans]
        alert_counts = (
            await self._alert_repo.count_by_scans(scan_ids) if scan_ids else {}
        )

        scan_summaries = []
        for scan in scans:
            # Note: port_count and event_count are not efficiently available
            # from list_by_host without N+1 queries or custom group_by repo methods.
            # For this simple version, they are left as None when not loaded.
            scan_summaries.append(
                ScanHistorySummary(
                    scan_id=scan.id,
                    timestamp=scan.started_at,
                    status=scan.status,
                    response_time_ms=scan.response_time_ms,
                    port_count=None,
                    event_count=None,
                    alert_count=alert_counts.get(scan.id, 0),
                )
            )

        return HostHistoryResult(
            host_id=host.id,
            address=host.address,
            name=host.name,
            enabled=host.enabled,
            scans=scan_summaries,
        )

    async def get_scan_details(self, scan_id: int) -> ScanDetailsResult | None:
        """Fetch full details for a specific scan, including ports, events and alerts.

        Parameters
        ----------
        scan_id:
            The primary key of the scan.

        Returns
        -------
        ScanDetailsResult | None
            The full details of the scan, or None if the scan does not exist.
        """
        scan = await self._scan_repo.get_by_id(scan_id)
        if scan is None:
            return None

        events = await self._event_repo.list_by_scan(scan_id)
        alerts = await self._alert_repo.list_by_scan(scan_id)

        port_summaries = [
            PortResultSummary(
                port=pr.port,
                status=pr.status,
                response_time_ms=pr.response_time_ms,
            )
            for pr in scan.port_results
        ]

        event_summaries = [
            EventSummary(
                event_type=ev.event_type,
                port=ev.port,
                previous_state=ev.previous_state,
                current_state=ev.current_state,
                created_at=ev.created_at,
            )
            for ev in events
        ]

        alert_summaries = [
            AlertSummary(
                id=al.id,
                alert_type=al.alert_type,
                severity=al.severity,
                message=al.message,
                port=al.port,
                created_at=al.created_at,
                monitoring_event_id=al.monitoring_event_id,
            )
            for al in alerts
        ]

        return ScanDetailsResult(
            scan_id=scan.id,
            status=scan.status,
            response_time_ms=scan.response_time_ms,
            started_at=scan.started_at,
            finished_at=scan.finished_at,
            ports=port_summaries,
            events=event_summaries,
            alerts=alert_summaries,
        )
