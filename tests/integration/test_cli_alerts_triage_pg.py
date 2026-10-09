"""Integration tests for CLI alert triage commands against PostgreSQL.

These tests require ``TEST_DATABASE_URL`` to be set and are tagged with the
``integration`` marker.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli import run_acknowledge_alert, run_resolve_alert
from app.core.config import settings
from app.detection.alerts import AlertStatus, AlertType, SecurityAlert, Severity
from app.monitoring.target import NetworkTarget
from app.repositories.alert import AlertRepository
from app.repositories.host import HostRepository

pytestmark = pytest.mark.integration

_BASE_TIME = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _make_alert(
    *,
    port: int = 80,
    timestamp: datetime = _BASE_TIME,
) -> SecurityAlert:
    return SecurityAlert(
        target=NetworkTarget.parse("10.0.0.1"),
        port=port,
        alert_type=AlertType.NEW_OPEN_PORT,
        severity=Severity.HIGH,
        message="Port 80 newly open",
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


@pytest.fixture(autouse=True)
def set_database_url(monkeypatch: pytest.MonkeyPatch, pg_session: AsyncSession) -> None:
    """Ensure DATABASE_URL is set and CLI functions share test session."""
    import os

    test_url = os.environ.get("TEST_DATABASE_URL", "")
    if test_url:
        monkeypatch.setattr(settings, "DATABASE_URL", test_url)

    @asynccontextmanager
    async def _mock_get_db_session():
        yield pg_session

    mock_engine = MagicMock()
    mock_engine.dispose = AsyncMock()

    monkeypatch.setattr("app.db.session.get_db_session", _mock_get_db_session)
    monkeypatch.setattr("app.db.session.get_engine", lambda: mock_engine)


class TestCliAlertsTriagePG:
    async def test_acknowledge_cli_pg(
        self,
        host_repo: HostRepository,
        pg_session: AsyncSession,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Confirm run_acknowledge_alert updates and commits ACKNOWLEDGED state."""
        alert_repo = AlertRepository(pg_session)
        host = await host_repo.create(address="10.0.0.1")
        created = await alert_repo.create(
            host_id=host.id,
            scan_id=None,
            monitoring_event_id=None,
            alert=_make_alert(port=80),
        )
        await pg_session.commit()

        code = await run_acknowledge_alert(created.id)
        assert code == 0

        captured = capsys.readouterr()
        assert f"Alert {created.id} acknowledged." in captured.out
        assert "Status: ACKNOWLEDGED" in captured.out

        # Verify DB persistence
        created_id = created.id
        pg_session.expire_all()
        refetched = await alert_repo.get_by_id(created_id)
        assert refetched is not None
        assert refetched.status == "ACKNOWLEDGED"
        assert refetched.status_enum == AlertStatus.ACKNOWLEDGED
        assert refetched.acknowledged_at is not None
        assert refetched.resolved_at is None

    async def test_resolve_acknowledged_cli_pg(
        self,
        host_repo: HostRepository,
        pg_session: AsyncSession,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Confirm run_resolve_alert transitions an acknowledged alert to RESOLVED."""
        alert_repo = AlertRepository(pg_session)
        host = await host_repo.create(address="10.0.0.1")
        created = await alert_repo.create(
            host_id=host.id,
            scan_id=None,
            monitoring_event_id=None,
            alert=_make_alert(port=80),
        )
        await pg_session.commit()

        # Step 1: Acknowledge
        await run_acknowledge_alert(created.id)

        # Step 2: Resolve
        code = await run_resolve_alert(created.id)
        assert code == 0

        captured = capsys.readouterr()
        assert f"Alert {created.id} resolved." in captured.out
        assert "Status: RESOLVED" in captured.out
        assert "Acknowledged at:" in captured.out
        assert "Resolved at:" in captured.out

        # Verify DB persistence
        created_id = created.id
        pg_session.expire_all()
        refetched = await alert_repo.get_by_id(created_id)
        assert refetched is not None
        assert refetched.status == "RESOLVED"
        assert refetched.status_enum == AlertStatus.RESOLVED
        assert refetched.acknowledged_at is not None
        assert refetched.resolved_at is not None

    async def test_direct_resolve_open_cli_pg(
        self,
        host_repo: HostRepository,
        pg_session: AsyncSession,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Confirm run_resolve_alert directly resolves an OPEN alert in PostgreSQL."""
        alert_repo = AlertRepository(pg_session)
        host = await host_repo.create(address="10.0.0.1")
        created = await alert_repo.create(
            host_id=host.id,
            scan_id=None,
            monitoring_event_id=None,
            alert=_make_alert(port=80),
        )
        await pg_session.commit()

        code = await run_resolve_alert(created.id)
        assert code == 0

        captured = capsys.readouterr()
        assert f"Alert {created.id} resolved." in captured.out
        assert "Status: RESOLVED" in captured.out
        assert "Acknowledged at:" not in captured.out
        assert "Resolved at:" in captured.out

        # Verify DB persistence
        created_id = created.id
        pg_session.expire_all()
        refetched = await alert_repo.get_by_id(created_id)
        assert refetched is not None
        assert refetched.status == "RESOLVED"
        assert refetched.acknowledged_at is None
        assert refetched.resolved_at is not None

    async def test_invalid_transition_leaves_db_record_intact_pg(
        self,
        host_repo: HostRepository,
        pg_session: AsyncSession,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Confirm invalid transition prints friendly error and leaves DB intact."""
        alert_repo = AlertRepository(pg_session)
        host = await host_repo.create(address="10.0.0.1")
        created = await alert_repo.create(
            host_id=host.id,
            scan_id=None,
            monitoring_event_id=None,
            alert=_make_alert(port=80),
        )
        created_id = created.id
        await pg_session.commit()

        # Direct resolve first
        await run_resolve_alert(created_id)

        # Attempting acknowledge on RESOLVED alert
        code = await run_acknowledge_alert(created_id)
        assert code == 1

        captured = capsys.readouterr()
        assert "Cannot transition alert" in captured.err

        # Verify DB state is still RESOLVED
        pg_session.expire_all()
        refetched = await alert_repo.get_by_id(created_id)
        assert refetched is not None
        assert refetched.status == "RESOLVED"
