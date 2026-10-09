"""ScanQueryService — read-only service for querying scans across all hosts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from app.monitoring.target import InvalidTargetError, NetworkTarget
from app.repositories.scan import ScanRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class ScanListItem:
    """Read-only presentation item for a scan in global listings."""

    id: int
    target: str
    status: str
    response_time_ms: float | None
    started_at: datetime
    finished_at: datetime | None


class ScanQueryService:
    """Read-only service for querying scans.

    Parameters
    ----------
    session:
        An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
    scan_repo:
        Optional :class:`~app.repositories.scan.ScanRepository` instance.
    """

    def __init__(
        self,
        session: AsyncSession,
        scan_repo: ScanRepository | None = None,
    ) -> None:
        self._session = session
        self._scan_repo = scan_repo or ScanRepository(session)

    async def list_scans(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        target: str | None = None,
    ) -> list[ScanListItem]:
        """Fetch global scans with pagination and optional target filter."""
        if limit <= 0:
            raise ValueError(f"limit must be a positive integer, got {limit!r}")
        if offset < 0:
            raise ValueError(f"offset must be non-negative, got {offset!r}")

        normalized_target: str | None = None
        if target is not None and target.strip():
            raw = target.strip()
            try:
                normalized_target = NetworkTarget.parse(raw).value
            except InvalidTargetError:
                normalized_target = raw

        records = await self._scan_repo.list_global(
            limit=limit,
            offset=offset,
            target=normalized_target,
        )

        return [
            ScanListItem(
                id=s.id,
                target=s.host.address if s.host is not None else "",
                status=s.status,
                response_time_ms=s.response_time_ms,
                started_at=s.started_at,
                finished_at=s.finished_at,
            )
            for s in records
        ]
