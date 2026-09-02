"""ScanRepository — data access layer for Scan and PortResult ORM models.

Design decisions
----------------

Session injection
    ``ScanRepository`` receives an ``AsyncSession`` at construction time.
    It never creates its own session.  The caller controls session lifetime
    and transaction boundaries.

Commit policy
    The repository executes ``add → flush`` (and ``refresh`` after ``create``)
    but **never commits**.  The caller decides when to call
    ``await session.commit()``.

    This allows future atomic writes spanning multiple models::

        scan = await scan_repo.create(...)
        await scan_repo.add_port_results(scan.id, results)
        await event_repo.create_many(...)
        await session.commit()  # all or nothing

Rollback policy
    After an ``IntegrityError`` the repository re-raises a domain exception
    **without rolling back**.  The session is in a broken state (PostgreSQL
    refuses further operations within the same transaction), so the **caller
    must rollback before reusing the session**::

        try:
            scan = await repo.create(host_id=999, ...)
        except ScanHostNotFoundError:
            await session.rollback()

Layer boundary: PortResultInput
    The repository must not import networking types (``TcpProbeResult``,
    ``PortStatus``, ``NetworkTarget``) — those belong to ``app/monitoring/``.
    ``PortResultInput`` is a minimal frozen dataclass that represents the three
    fields this layer needs.  The caller is responsible for converting domain
    objects to ``PortResultInput`` before calling ``add_port_results``.

Port ordering
    ``get_by_id`` loads ``port_results`` sorted ``ASC`` by port number via
    ``selectinload`` with an explicit ``order_by``.  This guarantees
    deterministic ordering (22, 80, 443, …) regardless of insertion order.

list_by_host ordering
    Returns scans ordered ``started_at DESC`` (most recent first).  This is the
    expected order for a monitoring history view.  ``port_results`` are *not*
    eagerly loaded here — only scan rows are returned, keeping the query cheap.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.port_result import PortResult
from app.models.scan import Scan

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input type — keeps the DB layer decoupled from app/monitoring/
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PortResultInput:
    """Minimal representation of a port probe result for persistence.

    The caller (a service or future CLI integration) is responsible for
    converting ``TcpProbeResult`` objects from ``app/monitoring/`` into this
    type before calling ``ScanRepository.add_port_results``.

    Parameters
    ----------
    port:
        TCP port number (1–65535).
    status:
        String value of the port status enum, e.g. ``"open"``, ``"closed"``,
        ``"timeout"``, ``"unreachable"``.
    response_time_ms:
        Duration of the probe in milliseconds, or ``None`` if unavailable.
    """

    port: int
    status: str
    response_time_ms: float | None


# ---------------------------------------------------------------------------
# Domain exception
# ---------------------------------------------------------------------------


class ScanHostNotFoundError(Exception):
    """Raised when creating a Scan with a host_id that does not exist.

    The underlying ``IntegrityError`` (FK violation) is chained as
    ``__cause__``.

    After catching this exception the caller **must** rollback the session
    before reusing it::

        try:
            scan = await repo.create(host_id=999, ...)
        except ScanHostNotFoundError:
            await session.rollback()
    """

    def __init__(self, host_id: int) -> None:
        self.host_id = host_id
        super().__init__(f"No host with id={host_id} exists.")


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class ScanRepository:
    """Data access layer for :class:`~app.models.scan.Scan` and
    :class:`~app.models.port_result.PortResult`.

    All database operations for scan history are centralised here.
    Application code must not write raw SQLAlchemy queries for scans.

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
        status: str,
        response_time_ms: float | None,
        started_at: datetime,
        finished_at: datetime | None,
    ) -> Scan:
        """Persist a new scan record and return it with server-side id populated.

        Parameters
        ----------
        host_id:
            Primary key of the associated host.  Must reference an existing row
            in ``hosts``.
        status:
            String representation of ``HostStatus`` (e.g. ``"available"``).
        response_time_ms:
            Estimated response time in milliseconds, or ``None``.
        started_at:
            Timestamp when the scan began (timezone-aware).
        finished_at:
            Timestamp when the scan completed, or ``None`` if interrupted.

        Returns
        -------
        Scan
            Newly created ORM instance with ``id`` populated after flush.

        Raises
        ------
        ScanHostNotFoundError
            If ``host_id`` does not reference a valid host (FK violation).
            The session is **not** rolled back — caller must do so.
        """
        scan = Scan(
            host_id=host_id,
            status=status,
            response_time_ms=response_time_ms,
            started_at=started_at,
            finished_at=finished_at,
        )
        self._session.add(scan)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            logger.debug("FK violation on scan create: host_id=%s", host_id)
            raise ScanHostNotFoundError(host_id) from exc
        await self._session.refresh(scan)
        logger.debug("Scan created: id=%s host_id=%s", scan.id, scan.host_id)
        return scan

    async def add_port_results(
        self,
        scan_id: int,
        results: list[PortResultInput],
    ) -> list[PortResult]:
        """Persist multiple port results for a scan in a single flush.

        All ``PortResult`` rows are added to the session before a single
        ``flush()`` is issued.  This avoids N round-trips for N ports.

        If ``results`` is empty no database operation is performed.

        Parameters
        ----------
        scan_id:
            Primary key of the scan these results belong to.
        results:
            List of :class:`PortResultInput` describing each port probe.

        Returns
        -------
        list[PortResult]
            The persisted ORM instances, in insertion order.
        """
        if not results:
            return []

        port_results = [
            PortResult(
                scan_id=scan_id,
                port=r.port,
                status=r.status,
                response_time_ms=r.response_time_ms,
            )
            for r in results
        ]
        for pr in port_results:
            self._session.add(pr)

        await self._session.flush()
        logger.debug(
            "PortResults added: scan_id=%s count=%d", scan_id, len(port_results)
        )
        return port_results

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_by_id(self, scan_id: int) -> Scan | None:
        """Return the scan with the given primary key, including its port results.

        ``port_results`` are loaded eagerly via ``selectinload`` so they are
        always safe to access in async contexts (avoids ``MissingGreenlet``
        errors from lazy loading).  Ports are ordered ``ASC`` by port number
        (sorted in Python after loading, since ``selectinload`` does not
        support ``order_by`` on the load option).

        Parameters
        ----------
        scan_id:
            Integer primary key.

        Returns
        -------
        Scan | None
            ``None`` if no scan with that id exists.
        """
        stmt = (
            select(Scan)
            .where(Scan.id == scan_id)
            .options(selectinload(Scan.port_results))
        )
        scan = cast(Scan | None, await self._session.scalar(stmt))
        if scan is not None:
            # Sort port_results in Python to guarantee ASC port order.
            # selectinload does not support order_by; Python sort is O(n log n)
            # and appropriate for the small number of ports per scan.
            scan.port_results.sort(key=lambda pr: pr.port)
        return scan

    async def list_by_host(
        self,
        host_id: int,
        *,
        limit: int | None = None,
    ) -> list[Scan]:
        """Return scans for a host, ordered most-recent first.

        Port results are **not** eagerly loaded — call ``get_by_id`` when
        port-level detail is needed.

        Parameters
        ----------
        host_id:
            Primary key of the host whose scan history is requested.
        limit:
            Maximum number of scans to return.  ``None`` returns all.
            Must be a positive integer when provided.

        Returns
        -------
        list[Scan]
            Scans ordered by ``started_at DESC`` (most recent first).

        Raises
        ------
        ValueError
            If ``limit`` is provided but is not a positive integer.
        """
        if limit is not None and limit <= 0:
            raise ValueError(f"limit must be a positive integer, got {limit!r}")

        stmt = (
            select(Scan).where(Scan.host_id == host_id).order_by(Scan.started_at.desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)

        result = await self._session.execute(stmt)
        return list(result.scalars().all())
