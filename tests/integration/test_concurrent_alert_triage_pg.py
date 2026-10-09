"""A concurrent acknowledgment must not overwrite a committed resolution."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.detection.alerts import (
    AlertType,
    InvalidAlertStateTransitionError,
    SecurityAlert,
    Severity,
)
from app.models.host import Host
from app.models.security_alert import SecurityAlertRecord
from app.monitoring.target import NetworkTarget
from app.repositories.alert import AlertRepository
from app.repositories.host import HostRepository
from app.services.alert_triage import AlertTriageService

pytestmark = pytest.mark.integration


async def test_acknowledge_waits_for_resolution_and_refreshes_cached_state(pg_engine):
    engine = create_async_engine(pg_engine.url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    target = NetworkTarget.parse(f"triage-{uuid4().hex}.test")
    locking = asyncio.Event()
    task = None

    class SignalingRepository(AlertRepository):
        async def get_by_id(self, alert_id, *, for_update=False):
            if for_update:
                locking.set()
            return await super().get_by_id(alert_id, for_update=for_update)

    try:
        async with sessions.begin() as session:
            host = await HostRepository(session).create(address=target.value)
            alert = await AlertRepository(session).create(
                host_id=host.id,
                scan_id=None,
                monitoring_event_id=None,
                alert=SecurityAlert(
                    target=target,
                    port=80,
                    alert_type=AlertType.NEW_OPEN_PORT,
                    severity=Severity.HIGH,
                    message="Concurrent triage regression",
                    timestamp=datetime.now(UTC),
                    source_event_type="port_opened",
                ),
            )
            alert_id = alert.id

        async with sessions() as resolver, sessions() as acknowledger:
            # Keep a stale OPEN object in the identity map of the waiting session.
            cached = await AlertRepository(acknowledger).get_by_id(alert_id)
            assert cached.status == "OPEN"
            await AlertRepository(resolver).get_by_id(alert_id, for_update=True)
            service = AlertTriageService(
                acknowledger, alert_repo=SignalingRepository(acknowledger)
            )
            task = asyncio.create_task(service.acknowledge(alert_id))
            await asyncio.wait_for(locking.wait(), timeout=5)
            done, _ = await asyncio.wait({task}, timeout=0.1)
            assert not done, "Acknowledgment must wait for the row lock"
            await AlertTriageService(resolver).resolve(alert_id)
            with pytest.raises(InvalidAlertStateTransitionError):
                await asyncio.wait_for(task, timeout=5)

        async with sessions() as session:
            final = await AlertRepository(session).get_by_id(alert_id)
            assert final.status == "RESOLVED"
            assert final.resolved_at is not None
            assert final.acknowledged_at is None
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        async with sessions.begin() as session:
            host_ids = select(Host.id).where(
                Host.address == target.value
            )
            await session.execute(
                delete(SecurityAlertRecord).where(
                    SecurityAlertRecord.host_id.in_(host_ids)
                )
            )
            await session.execute(delete(Host).where(Host.address == target.value))
        await engine.dispose()
