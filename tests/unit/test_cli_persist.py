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
    @patch("app.services.monitoring_persistence.MonitoringPersistenceService")
    async def test_monitor_without_persist_does_not_call_service(
        self,
        mock_svc_cls: MagicMock,
        mock_monitor_host: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Monitor without --persist should not use DB logic or call
        persistence service.
        """

        async def mock_generator():
            yield _make_snapshot()

        mock_monitor_host.return_value = mock_generator()

        with patch.dict(sys.modules, {"app.db.session": None}):
            # This would raise if it tries to import app.db.session
            code = await run_monitor("127.0.0.1", [80], 5, 1, False)
            assert code == 0

        mock_svc_cls.assert_not_called()
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
    async def test_first_snapshot_is_persisted_with_empty_events_and_alerts(
        self,
        mock_svc_cls: MagicMock,
        mock_get_engine: MagicMock,
        mock_get_db_session: MagicMock,
        mock_monitor_host: MagicMock,
    ) -> None:
        """First snapshot must persist with empty events and empty alerts."""
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
        mock_svc.persist_cycle.assert_called_once_with(snapshot, [], [])
        mock_engine.dispose.assert_called_once()

    @patch("app.cli.monitor_host")
    @patch("app.cli.detect_changes")
    @patch("app.db.session.get_db_session")
    @patch("app.db.session.get_engine")
    @patch("app.services.monitoring_persistence.MonitoringPersistenceService")
    async def test_second_snapshot_persists_with_events_and_alerts(
        self,
        mock_svc_cls: MagicMock,
        mock_get_engine: MagicMock,
        mock_get_db_session: MagicMock,
        mock_detect: MagicMock,
        mock_monitor_host: MagicMock,
    ) -> None:
        """Snapshot 2 with PORT_OPENED persists with PORT_OPENED event
        and NEW_OPEN_PORT/HIGH alert.
        """
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
        mock_detect.return_value = [event]

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
        mock_detect.assert_called_once_with(snap1, snap2)
        mock_svc.persist_cycle.assert_any_call(snap1, [], [])

        # Check call 2 kwargs/args
        call2_args = mock_svc.persist_cycle.call_args_list[1][0]
        assert call2_args[0] == snap2
        assert call2_args[1] == [event]
        assert len(call2_args[2]) == 1
        assert call2_args[2][0].alert_type.value == "new_open_port"
        assert call2_args[2][0].severity.value == "high"

    @patch("app.cli.monitor_host")
    @patch("app.cli.detect_changes")
    @patch("app.db.session.get_db_session")
    @patch("app.db.session.get_engine")
    @patch("app.services.monitoring_persistence.MonitoringPersistenceService")
    async def test_multiple_alerts_persisted(
        self,
        mock_svc_cls: MagicMock,
        mock_get_engine: MagicMock,
        mock_get_db_session: MagicMock,
        mock_detect: MagicMock,
        mock_monitor_host: MagicMock,
    ) -> None:
        """Cycle with multiple events persists all corresponding alerts."""
        settings.DATABASE_URL = "sqlite+aiosqlite:///:memory:"
        snap1 = _make_snapshot(port=80, status=PortStatus.OPEN)
        snap2 = _make_snapshot(port=80, status=PortStatus.CLOSED)

        async def mock_generator():
            yield snap1
            yield snap2

        mock_monitor_host.return_value = mock_generator()

        events = [
            MonitoringEvent(
                event_type=MonitoringEventType.PORT_CLOSED,
                target=NetworkTarget.parse("127.0.0.1"),
                timestamp=datetime.now(UTC),
                port=22,
                previous_state="open",
                current_state="closed",
            ),
            MonitoringEvent(
                event_type=MonitoringEventType.PORT_OPENED,
                target=NetworkTarget.parse("127.0.0.1"),
                timestamp=datetime.now(UTC),
                port=443,
                previous_state="closed",
                current_state="open",
            ),
            MonitoringEvent(
                event_type=MonitoringEventType.HOST_BECAME_UNAVAILABLE,
                target=NetworkTarget.parse("127.0.0.1"),
                timestamp=datetime.now(UTC),
                port=None,
                previous_state="available",
                current_state="unavailable",
            ),
        ]
        mock_detect.return_value = events

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

        call2_args = mock_svc.persist_cycle.call_args_list[1][0]
        assert call2_args[1] == events
        alerts = call2_args[2]
        assert len(alerts) == 3
        alert_types = [a.alert_type.value for a in alerts]
        assert alert_types == ["port_closed", "new_open_port", "host_down"]

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
        # Assert no password / secret leaked
        assert "secret" not in captured.err

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

    @patch("app.cli.monitor_host")
    @patch("app.cli.detect_changes")
    @patch("app.db.session.get_db_session")
    @patch("app.db.session.get_engine")
    @patch("app.services.monitoring_persistence.MonitoringPersistenceService")
    async def test_custom_alert_severity_persisted_in_cycle(
        self,
        mock_svc_cls: MagicMock,
        mock_get_engine: MagicMock,
        mock_get_db_session: MagicMock,
        mock_detect: MagicMock,
        mock_monitor_host: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Configured alert severity is forwarded to persistence service."""
        settings.DATABASE_URL = "sqlite+aiosqlite:///:memory:"
        monkeypatch.setattr(settings, "ALERT_SEVERITY_NEW_OPEN_PORT", "CRITICAL")
        snap1 = _make_snapshot(port=80, status=PortStatus.CLOSED)
        snap2 = _make_snapshot(port=80, status=PortStatus.OPEN)

        async def mock_generator():
            yield snap1
            yield snap2

        mock_monitor_host.return_value = mock_generator()

        event = MonitoringEvent(
            event_type=MonitoringEventType.PORT_OPENED,
            target=NetworkTarget.parse("127.0.0.1"),
            timestamp=datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC),
            port=80,
            previous_state="closed",
            current_state="open",
        )
        mock_detect.return_value = [event]

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

        call2_args = mock_svc.persist_cycle.call_args_list[1][0]
        assert len(call2_args[2]) == 1
        assert call2_args[2][0].alert_type.value == "new_open_port"
        assert call2_args[2][0].severity.value == "critical"

    @patch("app.cli.monitor_host")
    @patch("app.cli.detect_changes")
    @patch("app.db.session.get_db_session")
    @patch("app.db.session.get_engine")
    @patch("app.services.monitoring_persistence.MonitoringPersistenceService")
    async def test_expected_open_port_persisted_in_cycle(
        self,
        mock_svc_cls: MagicMock,
        mock_get_engine: MagicMock,
        mock_get_db_session: MagicMock,
        mock_detect: MagicMock,
        mock_monitor_host: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Expected open port alert is forwarded to persistence service."""
        settings.DATABASE_URL = "sqlite+aiosqlite:///:memory:"
        monkeypatch.setattr(settings, "EXPECTED_TCP_PORTS", "80")
        snap1 = _make_snapshot(port=80, status=PortStatus.CLOSED)
        snap2 = _make_snapshot(port=80, status=PortStatus.OPEN)

        async def mock_generator():
            yield snap1
            yield snap2

        mock_monitor_host.return_value = mock_generator()

        event = MonitoringEvent(
            event_type=MonitoringEventType.PORT_OPENED,
            target=NetworkTarget.parse("127.0.0.1"),
            timestamp=datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC),
            port=80,
            previous_state="closed",
            current_state="open",
        )
        mock_detect.return_value = [event]

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

        call2_args = mock_svc.persist_cycle.call_args_list[1][0]
        assert len(call2_args[2]) == 1
        assert call2_args[2][0].alert_type.value == "expected_open_port"
        assert call2_args[2][0].severity.value == "info"

    @patch("app.cli.monitor_host")
    @patch("app.cli.detect_changes")
    @patch("app.db.session.get_db_session")
    @patch("app.db.session.get_engine")
    @patch("app.services.monitoring_persistence.MonitoringPersistenceService")
    async def test_unexpected_open_port_persisted_in_cycle(
        self,
        mock_svc_cls: MagicMock,
        mock_get_engine: MagicMock,
        mock_get_db_session: MagicMock,
        mock_detect: MagicMock,
        mock_monitor_host: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Unexpected open port alert is forwarded to persistence service."""
        settings.DATABASE_URL = "sqlite+aiosqlite:///:memory:"
        monkeypatch.setattr(settings, "EXPECTED_TCP_PORTS", "443")
        snap1 = _make_snapshot(port=80, status=PortStatus.CLOSED)
        snap2 = _make_snapshot(port=80, status=PortStatus.OPEN)

        async def mock_generator():
            yield snap1
            yield snap2

        mock_monitor_host.return_value = mock_generator()

        event = MonitoringEvent(
            event_type=MonitoringEventType.PORT_OPENED,
            target=NetworkTarget.parse("127.0.0.1"),
            timestamp=datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC),
            port=80,
            previous_state="closed",
            current_state="open",
        )
        mock_detect.return_value = [event]

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

        call2_args = mock_svc.persist_cycle.call_args_list[1][0]
        assert len(call2_args[2]) == 1
        assert call2_args[2][0].alert_type.value == "unexpected_open_port"
        assert call2_args[2][0].severity.value == "high"
