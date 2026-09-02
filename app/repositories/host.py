"""HostRepository — data access layer for the Host ORM model.

Design decisions
----------------

Session injection
    ``HostRepository`` receives an ``AsyncSession`` at construction time.
    It never creates its own session.  The caller controls session lifetime
    and transaction boundaries.

Commit policy
    The repository executes ``add → flush → refresh`` but **never commits**.
    ``flush`` sends the SQL to the database within the current transaction,
    making server-generated values (``id``, ``created_at``) available without
    committing.  The caller decides when to call ``await session.commit()``.
    This allows future atomic writes spanning multiple models
    (e.g. Host + Scan + PortResult in one transaction).

Rollback policy
    After an ``IntegrityError`` (e.g. duplicate ``address``), the repository
    re-raises a ``HostAlreadyExistsError`` **without rolling back the session**.
    The session is in a broken state at that point (PostgreSQL will refuse
    further operations within the same transaction), so **the caller must
    rollback before reusing the session**::

        try:
            host = await repo.create(address="...")
        except HostAlreadyExistsError:
            await session.rollback()   # caller's responsibility
            ...

address immutability
    ``update()`` does not accept an ``address`` argument.  The address carries
    a UNIQUE constraint and serves as the business identifier for a monitored
    endpoint.  Silently re-addressing a host would corrupt historical scan
    data (scans would be attributed to an address that no longer matches).
    If a re-address use-case arises in a future version, it will be an
    explicit delete + re-create operation.
"""

from __future__ import annotations

import logging
from typing import cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.host import Host

# ---------------------------------------------------------------------------
# Sentinel for optional update parameters
# ---------------------------------------------------------------------------


class _Unset:
    """Singleton sentinel used to distinguish 'not passed' from ``None``.

    This avoids ``Literal["_unset"]`` string sentinels, which are fragile
    and generate unnecessary ``type: ignore`` suppression comments under
    mypy strict mode.
    """


_UNSET = _Unset()

logger = logging.getLogger(__name__)


class HostAlreadyExistsError(Exception):
    """Raised when attempting to create a Host with a duplicate address.

    The underlying ``IntegrityError`` is chained as the ``__cause__``.

    After catching this exception the caller **must** rollback the session
    before reusing it::

        try:
            host = await repo.create(address="192.168.0.10")
        except HostAlreadyExistsError:
            await session.rollback()
    """

    def __init__(self, address: str) -> None:
        self.address = address
        super().__init__(f"A host with address {address!r} already exists.")


class HostRepository:
    """Data access layer for :class:`~app.models.host.Host`.

    All database operations for ``Host`` records are centralised here.
    Application code must not construct raw SQLAlchemy queries for hosts.

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

    async def create(self, *, address: str, name: str | None = None) -> Host:
        """Persist a new host and return it with all server-side fields filled.

        The ``enabled`` default (``True``) comes from the ORM model column
        definition; it is not replicated here.

        Parameters
        ----------
        address:
            Network address (IP or hostname).  Must be unique across all hosts.
        name:
            Optional human-readable label for the host.

        Returns
        -------
        Host
            The newly created ORM instance with ``id``, ``created_at``, and
            ``enabled`` populated.

        Raises
        ------
        HostAlreadyExistsError
            If a host with the same ``address`` already exists.  The session
            is **not** rolled back — the caller must do so before reusing it.
        """
        host = Host(address=address, name=name)
        self._session.add(host)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            logger.debug("Duplicate address on create: %r", address)
            raise HostAlreadyExistsError(address) from exc
        await self._session.refresh(host)
        logger.debug("Host created: id=%s address=%r", host.id, host.address)
        return host

    async def update(
        self,
        host: Host,
        *,
        name: str | None | _Unset = _UNSET,
        enabled: bool | _Unset = _UNSET,
    ) -> Host:
        """Update mutable fields on an existing host.

        Only ``name`` and ``enabled`` may be changed.  ``address`` is
        intentionally excluded — see module docstring for rationale.

        Passing no value (the default ``_UNSET`` sentinel) leaves that field
        unchanged.  Pass ``None`` explicitly to clear ``name``.

        Parameters
        ----------
        host:
            The ``Host`` ORM instance to update.  Must belong to the current
            session.
        name:
            New human-readable label, or ``None`` to clear it.
        enabled:
            ``True`` to enable monitoring; ``False`` to disable.

        Returns
        -------
        Host
            The same instance, with updated fields and ``updated_at`` refreshed
            after the flush.
        """
        if not isinstance(name, _Unset):
            host.name = name
        if not isinstance(enabled, _Unset):
            host.enabled = enabled

        self._session.add(host)
        await self._session.flush()
        await self._session.refresh(host)
        logger.debug("Host updated: id=%s", host.id)
        return host

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_by_id(self, host_id: int) -> Host | None:
        """Return the host with the given primary key, or ``None`` if absent.

        Parameters
        ----------
        host_id:
            Integer primary key.

        Returns
        -------
        Host | None
        """
        return await self._session.get(Host, host_id)

    async def get_by_address(self, address: str) -> Host | None:
        """Return the host with the given address, or ``None`` if absent.

        The query respects the ``UNIQUE`` constraint on ``hosts.address``;
        at most one row can match.

        Parameters
        ----------
        address:
            Network address as stored (exact match).

        Returns
        -------
        Host | None
        """
        stmt = select(Host).where(Host.address == address)
        return cast(Host | None, await self._session.scalar(stmt))

    async def list(self, *, enabled: bool | None = None) -> list[Host]:
        """Return all hosts, ordered deterministically by ``id``.

        Parameters
        ----------
        enabled:
            When ``True``, return only active hosts.
            When ``False``, return only disabled hosts.
            When ``None`` (default), return all hosts regardless of state.

        Returns
        -------
        list[Host]
        """
        stmt = select(Host).order_by(Host.id)
        if enabled is not None:
            stmt = stmt.where(Host.enabled == enabled)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
