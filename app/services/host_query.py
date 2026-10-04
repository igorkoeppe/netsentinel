"""HostQueryService — read-only service for querying monitored hosts.

Provides decoupled DTOs for host listing without exposing ORM objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from app.repositories.host import HostRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class HostItem:
    """Read-only presentation item for a host."""

    id: int
    name: str | None
    address: str
    enabled: bool
    created_at: datetime
    updated_at: datetime | None


class HostQueryService:
    """Read-only service for querying hosts.

    Parameters
    ----------
    session:
        An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
    host_repo:
        Optional :class:`~app.repositories.host.HostRepository` instance.
    """

    def __init__(
        self,
        session: AsyncSession,
        host_repo: HostRepository | None = None,
    ) -> None:
        self._session = session
        self._host_repo = host_repo or HostRepository(session)

    async def list_hosts(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        enabled: bool | None = None,
    ) -> list[HostItem]:
        """Fetch hosts with pagination and optional enabled filter."""
        if limit <= 0:
            raise ValueError(f"limit must be a positive integer, got {limit!r}")
        if offset < 0:
            raise ValueError(f"offset must be non-negative, got {offset!r}")

        records = await self._host_repo.list(
            enabled=enabled,
            limit=limit,
            offset=offset,
        )
        return [
            HostItem(
                id=h.id,
                name=h.name,
                address=h.address,
                enabled=h.enabled,
                created_at=h.created_at,
                updated_at=h.updated_at,
            )
            for h in records
        ]
