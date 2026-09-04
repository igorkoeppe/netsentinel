"""Two first-time monitors must both commit against a dedicated PostgreSQL DB."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.host import Host
from app.models.monitoring_event import MonitoringEventRecord
from app.models.port_result import PortResult
from app.models.scan import Scan
from app.monitoring.availability import HostAvailabilityResult, HostStatus
from app.monitoring.port_scanner import PortScanResult
from app.monitoring.target import NetworkTarget
from app.repositories.host import HostRepository
from app.services.monitoring_persistence import MonitoringPersistenceService

pytestmark = pytest.mark.integration


async def test_two_first_cycles_commit_for_same_host(pg_engine):
    # Fresh connections avoid sharing asyncpg connections across pytest loops.
    engine = create_async_engine(pg_engine.url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    target = NetworkTarget.parse(f"race-{uuid4().hex}.test")
    now = datetime.now(UTC)
    snapshot = HostAvailabilityResult(
        target=target,
        status=HostStatus.UNAVAILABLE,
        response_time_ms=0,
        scan_result=PortScanResult(target, now, now, 0),
    )
    ready = asyncio.Event()
    reads = 0
    original_get = HostRepository.get_by_address

    async def synchronized_get(repo, address):
        nonlocal reads
        host = await original_get(repo, address)
        if host is None and reads < 2:
            reads += 1
            if reads == 2:
                ready.set()
            await ready.wait()
        return host

    async def persist():
        async with sessions() as session:
            return await MonitoringPersistenceService(session).persist_cycle(
                snapshot, []
            )

    try:
        with patch.object(HostRepository, "get_by_address", synchronized_get):
            first, second = await asyncio.wait_for(
                asyncio.gather(persist(), persist()), timeout=10
            )
        assert first.host.id == second.host.id
        assert first.scan.id != second.scan.id
        async with sessions() as session:
            scans = await session.scalars(
                select(Scan).where(Scan.host_id == first.host.id)
            )
            assert len(scans.all()) == 2
    finally:
        # Remove only this test's random host; never truncate shared tables.
        async with sessions.begin() as session:
            host_ids = select(Host.id).where(Host.address == target.value)
            scan_ids = select(Scan.id).where(Scan.host_id.in_(host_ids))
            await session.execute(
                delete(MonitoringEventRecord).where(
                    MonitoringEventRecord.host_id.in_(host_ids)
                )
            )
            await session.execute(
                delete(PortResult).where(PortResult.scan_id.in_(scan_ids))
            )
            await session.execute(delete(Scan).where(Scan.host_id.in_(host_ids)))
            await session.execute(delete(Host).where(Host.address == target.value))
        await engine.dispose()
