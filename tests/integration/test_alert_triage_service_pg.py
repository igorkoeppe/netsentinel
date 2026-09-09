"""Integration tests for AlertTriageService against PostgreSQL.

These tests require ``TEST_DATABASE_URL`` to be set and are tagged with the
``integration`` marker.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.detection.alerts import (
    AlertStatus,
    AlertType,
    InvalidAlertStateTransitionError,
    SecurityAlert,
    Severity,
)
from app.monitoring.target import NetworkTarget
from app.repositories.alert import AlertRepository
from app.repositories.host import HostRepository
from app.services.alert_triage import (
    AlertNotFoundError,
    AlertTriageService,
)

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_TARGET = NetworkTarget.parse("10.0.0.1")


def _port_alert(port: int = 80, *, timestamp: datetime = _NOW) -> SecurityAlert:
    return SecurityAlert(
        target=_TARGET,
        port=port,
        alert_type=AlertType.NEW_OPEN_PORT,
        severity=Severity.HIGH,
        message=f"TCP port {port} is newly open.",
        timestamp=timestamp,
        source_event_type="port_opened",
    )


@pytest.fixture(autouse=True)
async def cleanup_db(pg_session: AsyncSession) -> None:
    """Clean up tables before and after each integration test."""
    await pg_session.execute(text("TRUNCATE TABLE security_alerts CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE monitoring_events CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE port_results CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE scans CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE hosts CASCADE"))
    await pg_session.commit()
    yield
    await pg_session.execute(text("TRUNCATE TABLE security_alerts CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE monitoring_events CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE port_results CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE scans CASCADE"))
    await pg_session.execute(text("TRUNCATE TABLE hosts CASCADE"))
    await pg_session.commit()


@pytest.fixture
async def triage_service(pg_session: AsyncSession) -> AlertTriageService:
    return AlertTriageService(pg_session)


class TestAlertTriageServicePG:
    async def test_get_alert_persisted(
        self,
        triage_service: AlertTriageService,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        alert_repo = AlertRepository(pg_session)
        host = await host_repo.create(address="10.10.0.1")
        created = await alert_repo.create(
            host_id=host.id,
            scan_id=None,
            monitoring_event_id=None,
            alert=_port_alert(80),
        )
        await pg_session.commit()

        fetched = await triage_service.get_alert(created.id)
        assert fetched.id == created.id
        assert fetched.status == "OPEN"
        assert fetched.status_enum == AlertStatus.OPEN
        assert fetched.acknowledged_at is None
        assert fetched.resolved_at is None

    async def test_get_alert_not_found(
        self,
        triage_service: AlertTriageService,
    ) -> None:
        with pytest.raises(AlertNotFoundError) as exc_info:
            await triage_service.get_alert(999_999)

        assert exc_info.value.alert_id == 999_999

    async def test_acknowledge_persisted_alert(
        self,
        triage_service: AlertTriageService,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        alert_repo = AlertRepository(pg_session)
        host = await host_repo.create(address="10.10.0.2")
        created = await alert_repo.create(
            host_id=host.id,
            scan_id=None,
            monitoring_event_id=None,
            alert=_port_alert(80),
        )
        await pg_session.commit()

        ack_time = _NOW + timedelta(minutes=5)
        updated = await triage_service.acknowledge(created.id, at=ack_time)

        assert updated.id == created.id
        assert updated.status == "ACKNOWLEDGED"
        assert updated.status_enum == AlertStatus.ACKNOWLEDGED
        assert updated.acknowledged_at == ack_time
        assert updated.resolved_at is None

        # Verify persistence across a fresh session read
        created_id = created.id
        pg_session.expire_all()
        refetched = await alert_repo.get_by_id(created_id)
        assert refetched is not None
        assert refetched.status == "ACKNOWLEDGED"
        assert refetched.acknowledged_at == ack_time
        assert refetched.resolved_at is None

    async def test_resolve_acknowledged_alert(
        self,
        triage_service: AlertTriageService,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        alert_repo = AlertRepository(pg_session)
        host = await host_repo.create(address="10.10.0.3")
        created = await alert_repo.create(
            host_id=host.id,
            scan_id=None,
            monitoring_event_id=None,
            alert=_port_alert(80),
        )
        await pg_session.commit()

        ack_time = _NOW + timedelta(minutes=5)
        await triage_service.acknowledge(created.id, at=ack_time)

        res_time = _NOW + timedelta(minutes=15)
        resolved = await triage_service.resolve(created.id, at=res_time)

        assert resolved.id == created.id
        assert resolved.status == "RESOLVED"
        assert resolved.status_enum == AlertStatus.RESOLVED
        assert resolved.acknowledged_at == ack_time
        assert resolved.resolved_at == res_time

        created_id = created.id
        pg_session.expire_all()
        refetched = await alert_repo.get_by_id(created_id)
        assert refetched is not None
        assert refetched.status == "RESOLVED"
        assert refetched.acknowledged_at == ack_time
        assert refetched.resolved_at == res_time

    async def test_direct_resolve_from_open(
        self,
        triage_service: AlertTriageService,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        alert_repo = AlertRepository(pg_session)
        host = await host_repo.create(address="10.10.0.4")
        created = await alert_repo.create(
            host_id=host.id,
            scan_id=None,
            monitoring_event_id=None,
            alert=_port_alert(80),
        )
        await pg_session.commit()

        res_time = _NOW + timedelta(minutes=10)
        resolved = await triage_service.resolve(created.id, at=res_time)

        assert resolved.id == created.id
        assert resolved.status == "RESOLVED"
        assert resolved.status_enum == AlertStatus.RESOLVED
        assert resolved.acknowledged_at is None
        assert resolved.resolved_at == res_time

        created_id = created.id
        pg_session.expire_all()
        refetched = await alert_repo.get_by_id(created_id)
        assert refetched is not None
        assert refetched.status == "RESOLVED"
        assert refetched.acknowledged_at is None
        assert refetched.resolved_at == res_time

    async def test_acknowledge_invalid_transition_triggers_rollback(
        self,
        triage_service: AlertTriageService,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        alert_repo = AlertRepository(pg_session)
        host = await host_repo.create(address="10.10.0.5")
        created = await alert_repo.create(
            host_id=host.id,
            scan_id=None,
            monitoring_event_id=None,
            alert=_port_alert(80),
        )
        await pg_session.commit()

        # Resolve first
        res_time = _NOW + timedelta(minutes=10)
        await triage_service.resolve(created.id, at=res_time)

        # Attempting acknowledge on RESOLVED alert must fail
        with pytest.raises(InvalidAlertStateTransitionError):
            await triage_service.acknowledge(created.id)

        created_id = created.id
        pg_session.expire_all()
        refetched = await alert_repo.get_by_id(created_id)
        assert refetched is not None
        assert refetched.status == "RESOLVED"

    async def test_resolve_invalid_transition_triggers_rollback(
        self,
        triage_service: AlertTriageService,
        host_repo: HostRepository,
        pg_session: AsyncSession,
    ) -> None:
        alert_repo = AlertRepository(pg_session)
        host = await host_repo.create(address="10.10.0.6")
        created = await alert_repo.create(
            host_id=host.id,
            scan_id=None,
            monitoring_event_id=None,
            alert=_port_alert(80),
        )
        await pg_session.commit()

        # Resolve first
        res_time = _NOW + timedelta(minutes=10)
        await triage_service.resolve(created.id, at=res_time)

        # Attempting resolve on already RESOLVED alert must fail
        with pytest.raises(InvalidAlertStateTransitionError):
            await triage_service.resolve(created.id)

        created_id = created.id
        pg_session.expire_all()
        refetched = await alert_repo.get_by_id(created_id)
        assert refetched is not None
        assert refetched.status == "RESOLVED"

    async def test_acknowledge_nonexistent_alert_raises_not_found(
        self,
        triage_service: AlertTriageService,
    ) -> None:
        with pytest.raises(AlertNotFoundError) as exc_info:
            await triage_service.acknowledge(999_999)

        assert exc_info.value.alert_id == 999_999

    async def test_resolve_nonexistent_alert_raises_not_found(
        self,
        triage_service: AlertTriageService,
    ) -> None:
        with pytest.raises(AlertNotFoundError) as exc_info:
            await triage_service.resolve(999_999)

        assert exc_info.value.alert_id == 999_999
