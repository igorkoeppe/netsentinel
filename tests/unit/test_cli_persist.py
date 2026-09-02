import asyncio
import sys
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.cli import run_monitor
from app.core.config import settings
from app.detection.engine import MonitoringEvent, MonitoringEventType
from app.monitoring.availability import HostAvailabilityResult, HostStatus
from app.monitoring.port_scanner import PortScanResult
from app.monitoring.target import NetworkTarget
from app.monitoring.tcp_probe import PortStatus, TcpProbeResult

UTC = UTC


def _make_snapshot(
    target_str="127.0.0.1", port=80, status=PortStatus.OPEN
) -> HostAvailabilityResult:
    target = NetworkTarget.parse(target_str)
    return HostAvailabilityResult(
        target=target,
        status=HostStatus.AVAILABLE,
        response_time_ms=1.5,
        scan_result=PortScanResult(
            target=target,
            started_at=datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC),
            finished_at=datetime.now(UTC),
            duration_ms=10.0,
            ports=(TcpProbeResult(target, port, status, 2.0),),
        ),
    )


class TestCliPersist:
    @patch("app.cli.monitor_host")
    async def test_monitor_without_persist_does_not_load_db(
        self, mock_monitor_host: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Monitor without --persist should not use DB logic."""

        async def mock_generator():
            yield _make_snapshot()

        mock_monitor_host.return_value = mock_generator()

        with patch.dict(sys.modules, {"app.db.session": None}):
            # This would raise if it tries to import app.db.session
            code = await run_monitor("127.0.0.1", [80], 5, 1, False)
            assert code == 0

        captured = capsys.readouterr()
        assert "Persistence: enabled" not in captured.out

    @patch("app.cli.monitor_host")
    async def test_missing_database_url_fails_fast(
        self, mock_monitor_host: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """If --persist is true but DATABASE_URL is missing, it should fail nicely."""
        settings.DATABASE_URL = ""

        code = await run_monitor("127.0.0.1", [80], 5, 1, True)
        assert code == 1

        captured = capsys.readouterr()
        assert (
            "error: DATABASE_URL is required when --persist is enabled" in captured.err
        )
        # reset for other tests
        settings.DATABASE_URL = "sqlite+aiosqlite:///:memory:"

    @patch("app.cli.monitor_host")
    @patch("app.db.session.get_db_session")
    @patch("app.db.session.get_engine")
    @patch("app.services.monitoring_persistence.MonitoringPersistenceService")
    async def test_first_snapshot_is_persisted_with_empty_events(
        self,
        mock_svc_cls: MagicMock,
        mock_get_engine: MagicMock,
        mock_get_db_session: MagicMock,
        mock_monitor_host: MagicMock,
    ) -> None:
        settings.DATABASE_URL = "sqlite+aiosqlite:///:memory:"
        snapshot = _make_snapshot()

        async def mock_generator():
            yield snapshot

        mock_monitor_host.return_value = mock_generator()

        mock_session_ctx = MagicMock()
        mock_get_db_session.return_value = mock_session_ctx
        mock_session = MagicMock()
        mock_session_ctx.__aenter__.return_value = mock_session

        mock_svc = MagicMock()
        mock_svc.persist_cycle = AsyncMock()
        mock_svc_cls.return_value = mock_svc

        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        code = await run_monitor("127.0.0.1", [80], 5, 1, True)
        assert code == 0

        mock_svc_cls.assert_called_with(mock_session)
        mock_svc.persist_cycle.assert_called_once_with(snapshot, [])
        mock_engine.dispose.assert_called_once()

    @patch("app.cli.monitor_host")
    @patch("app.cli.detect_changes")
    @patch("app.db.session.get_db_session")
    @patch("app.db.session.get_engine")
    @patch("app.services.monitoring_persistence.MonitoringPersistenceService")
    async def test_second_snapshot_persists_with_events(
        self,
        mock_svc_cls: MagicMock,
        mock_get_engine: MagicMock,
        mock_get_db_session: MagicMock,
        mock_detect: MagicMock,
        mock_monitor_host: MagicMock,
    ) -> None:
        settings.DATABASE_URL = "sqlite+aiosqlite:///:memory:"
        snap1 = _make_snapshot(port=80, status=PortStatus.CLOSED)
        snap2 = _make_snapshot(port=80, status=PortStatus.OPEN)

        async def mock_generator():
            yield snap1
            yield snap2

        mock_monitor_host.return_value = mock_generator()

        event = MonitoringEvent(
            event_type=MonitoringEventType.PORT_OPENED,
            target=NetworkTarget.parse("127.0.0.1"),
            timestamp=datetime.now(UTC),
            port=80,
            previous_state="closed",
            current_state="open",
        )
        mock_detect.side_effect = [[], [event]]

        mock_session_ctx = MagicMock()
        mock_get_db_session.return_value = mock_session_ctx
        mock_session = MagicMock()
        mock_session_ctx.__aenter__.return_value = mock_session

        mock_svc = MagicMock()
        mock_svc.persist_cycle = AsyncMock()
        mock_svc_cls.return_value = mock_svc

        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        code = await run_monitor("127.0.0.1", [80], 5, 2, True)
        assert code == 0

        assert mock_svc.persist_cycle.call_count == 2
        from unittest.mock import ANY

        mock_svc.persist_cycle.assert_any_call(ANY, [])
        mock_svc.persist_cycle.assert_any_call(ANY, ANY)

    @patch("app.cli.monitor_host")
    @patch("app.db.session.get_db_session")
    @patch("app.db.session.get_engine")
    @patch("app.services.monitoring_persistence.MonitoringPersistenceService")
    async def test_persistence_failure_stops_monitor_and_exits(
        self,
        mock_svc_cls: MagicMock,
        mock_get_engine: MagicMock,
        mock_get_db_session: MagicMock,
        mock_monitor_host: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        settings.DATABASE_URL = "sqlite+aiosqlite:///:memory:"
        snap1 = _make_snapshot()

        async def mock_generator():
            yield snap1
            yield snap1

        mock_monitor_host.return_value = mock_generator()

        mock_session_ctx = MagicMock()
        mock_get_db_session.return_value = mock_session_ctx
        mock_session_ctx.__aenter__.return_value = MagicMock()

        mock_svc = MagicMock()
        mock_svc.persist_cycle = AsyncMock(
            side_effect=IntegrityError("fake db error", {}, None)
        )
        mock_svc_cls.return_value = mock_svc

        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        code = await run_monitor("127.0.0.1", [80], 5, 2, True)
        assert code == 1

        captured = capsys.readouterr()
        assert "fake db error" in captured.err

    @patch("app.cli.monitor_host")
    @patch("app.db.session.get_db_session")
    @patch("app.db.session.get_engine")
    @patch("app.services.monitoring_persistence.MonitoringPersistenceService")
    async def test_cancellation_with_persist_cleans_up(
        self,
        mock_svc_cls: MagicMock,
        mock_get_engine: MagicMock,
        mock_get_db_session: MagicMock,
        mock_monitor_host: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        settings.DATABASE_URL = "sqlite+aiosqlite:///:memory:"

        async def mock_generator():
            raise asyncio.CancelledError()
            yield  # type: ignore

        mock_monitor_host.return_value = mock_generator()
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        code = await run_monitor("127.0.0.1", [80], 5, 1, True)
        assert code == 0

        mock_engine.dispose.assert_called_once()
