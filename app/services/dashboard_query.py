"""DashboardQueryService — aggregated metrics service for the operational overview."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from app.repositories.alert import AlertRepository
from app.repositories.host import HostRepository
from app.repositories.scan import ScanRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class HostsSummaryResult:
    total: int
    enabled: int
    disabled: int


@dataclass(frozen=True)
class ScansSummaryResult:
    total: int
    last_scan_at: datetime | None


@dataclass(frozen=True)
class AlertsSummaryResult:
    total: int
    by_status: dict[str, int]
    by_severity: dict[str, int]


@dataclass(frozen=True)
class DashboardSummaryResult:
    hosts: HostsSummaryResult
    scans: ScansSummaryResult
    alerts: AlertsSummaryResult


class DashboardQueryService:
    """Read-only service for dashboard operational aggregations.

    Executes aggregation queries in PostgreSQL without loading entire tables
    into memory.

    Parameters
    ----------
    session:
        An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
    """

    def __init__(
        self,
        session: AsyncSession,
        host_repo: HostRepository | None = None,
        scan_repo: ScanRepository | None = None,
        alert_repo: AlertRepository | None = None,
    ) -> None:
        self._session = session
        self._host_repo = host_repo or HostRepository(session)
        self._scan_repo = scan_repo or ScanRepository(session)
        self._alert_repo = alert_repo or AlertRepository(session)

    async def get_summary(self) -> DashboardSummaryResult:
        """Aggregate operational metrics across hosts, scans, and alerts."""
        hosts_data = await self._host_repo.get_summary()
        scans_data = await self._scan_repo.get_summary()
        alerts_data = await self._alert_repo.get_summary()

        return DashboardSummaryResult(
            hosts=HostsSummaryResult(
                total=hosts_data["total"],
                enabled=hosts_data["enabled"],
                disabled=hosts_data["disabled"],
            ),
            scans=ScansSummaryResult(
                total=scans_data["total"],
                last_scan_at=scans_data["last_scan_at"],
            ),
            alerts=AlertsSummaryResult(
                total=alerts_data["total"],
                by_status=alerts_data["by_status"],
                by_severity=alerts_data["by_severity"],
            ),
        )
