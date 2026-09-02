"""Unit tests for the CLI history commands."""

import argparse
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from app.cli import main, parse_limit, run_history
from app.core.config import settings
from app.services.history import (
    EventSummary,
    HostHistoryResult,
    PortResultSummary,
    ScanDetailsResult,
    ScanHistorySummary,
)


class TestParseLimit:
    def test_valid_limit(self) -> None:
        assert parse_limit("10") == 10
        assert parse_limit("1") == 1

    def test_invalid_string(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError, match="Invalid limit: 'abc'"):
            parse_limit("abc")

    def test_zero_limit(self) -> None:
        with pytest.raises(
            argparse.ArgumentTypeError, match="Limit must be strictly positive"
        ):
            parse_limit("0")

    def test_negative_limit(self) -> None:
        with pytest.raises(
            argparse.ArgumentTypeError, match="Limit must be strictly positive"
        ):
            parse_limit("-1")


class TestRunHistory:
    @pytest.fixture(autouse=True)
    def setup_db_url(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "DATABASE_URL", "postgresql+asyncpg://mock")

    async def test_no_db_url(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(settings, "DATABASE_URL", "")
        code = await run_history("127.0.0.1", None, 10)
        assert code == 1
        captured = capsys.readouterr()
        assert "error: DATABASE_URL is required for history queries" in captured.err

    async def test_missing_target_and_scan(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = await run_history(None, None, 10)
        assert code == 2
        captured = capsys.readouterr()
        assert "error: must provide either TARGET or --scan" in captured.err

    async def test_invalid_target(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = await run_history("http://example.com", None, 10)
        assert code == 2
        captured = capsys.readouterr()
        assert "error: invalid network target" in captured.err

    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.history.HistoryService")
    async def test_db_connection_failure(
        self,
        mock_svc_cls: MagicMock,
        mock_get_session: MagicMock,
        mock_get_engine: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        mock_svc_cls.side_effect = OperationalError("fake", {}, None)

        # Mock async context manager for get_db_session
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__.side_effect = OperationalError("fake", {}, None)
        mock_get_session.return_value = mock_session_ctx

        code = await run_history("127.0.0.1", None, 10)
        assert code == 1
        captured = capsys.readouterr()
        assert "error: could not connect to PostgreSQL database" in captured.err
        assert "fake" not in captured.err
        mock_engine.dispose.assert_called_once()

    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.history.HistoryService")
    async def test_host_not_found(
        self,
        mock_svc_cls: MagicMock,
        mock_get_session: MagicMock,
        mock_get_engine: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        mock_svc = MagicMock()
        mock_svc.get_host_history = AsyncMock(return_value=None)
        mock_svc_cls.return_value = mock_svc

        mock_session = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__.return_value = mock_session
        mock_get_session.return_value = mock_session_ctx

        code = await run_history("10.10.10.10", None, 10)
        assert code == 0
        captured = capsys.readouterr()
        assert "No persisted history found for 10.10.10.10." in captured.out

    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.history.HistoryService")
    async def test_host_without_scans(
        self,
        mock_svc_cls: MagicMock,
        mock_get_session: MagicMock,
        mock_get_engine: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        host_result = HostHistoryResult(
            host_id=1, address="127.0.0.1", name=None, enabled=True, scans=[]
        )
        mock_svc = MagicMock()
        mock_svc.get_host_history = AsyncMock(return_value=host_result)
        mock_svc_cls.return_value = mock_svc

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__.return_value = AsyncMock()
        mock_get_session.return_value = mock_session_ctx

        code = await run_history("127.0.0.1", None, 10)
        assert code == 0
        captured = capsys.readouterr()
        assert "Target: 127.0.0.1" in captured.out
        assert "No scans recorded." in captured.out

    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.history.HistoryService")
    async def test_host_with_scans(
        self,
        mock_svc_cls: MagicMock,
        mock_get_session: MagicMock,
        mock_get_engine: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        scan = ScanHistorySummary(
            scan_id=42,
            timestamp=datetime(2026, 9, 2, 19, 20, 0, tzinfo=UTC),
            status="available",
            response_time_ms=1.2,
            port_count=3,
            event_count=1,
        )
        host_result = HostHistoryResult(
            host_id=1, address="127.0.0.1", name=None, enabled=True, scans=[scan]
        )
        mock_svc = MagicMock()
        mock_svc.get_host_history = AsyncMock(return_value=host_result)
        mock_svc_cls.return_value = mock_svc

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__.return_value = AsyncMock()
        mock_get_session.return_value = mock_session_ctx

        code = await run_history("127.0.0.1", None, 10)
        assert code == 0
        captured = capsys.readouterr()
        assert "NetSentinel History" in captured.out
        assert "Target: 127.0.0.1" in captured.out
        assert "SCAN" in captured.out
        assert "STATUS" in captured.out
        assert "42" in captured.out
        assert "AVAILABLE" in captured.out
        assert "3" in captured.out
        assert "1" in captured.out

    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.history.HistoryService")
    async def test_scan_not_found(
        self,
        mock_svc_cls: MagicMock,
        mock_get_session: MagicMock,
        mock_get_engine: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        mock_svc = MagicMock()
        mock_svc.get_scan_details = AsyncMock(return_value=None)
        mock_svc_cls.return_value = mock_svc

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__.return_value = AsyncMock()
        mock_get_session.return_value = mock_session_ctx

        code = await run_history(None, 999999, 10)
        assert code == 0
        captured = capsys.readouterr()
        assert "Scan not found." in captured.out

    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.history.HistoryService")
    async def test_scan_details(
        self,
        mock_svc_cls: MagicMock,
        mock_get_session: MagicMock,
        mock_get_engine: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        ports = [
            PortResultSummary(port=22, status="closed", response_time_ms=0.8),
            PortResultSummary(port=80, status="open", response_time_ms=1.0),
            PortResultSummary(port=443, status="open", response_time_ms=1.2),
        ]
        events = [
            EventSummary(
                event_type="port_opened",
                port=443,
                previous_state="closed",
                current_state="open",
                created_at=datetime(2026, 9, 2, 19, 20, 0, tzinfo=UTC),
            ),
            EventSummary(
                event_type="host_became_available",
                port=None,
                previous_state="unavailable",
                current_state="available",
                created_at=datetime(2026, 9, 2, 19, 20, 0, tzinfo=UTC),
            ),
        ]
        details = ScanDetailsResult(
            scan_id=42,
            status="available",
            response_time_ms=1.2,
            started_at=datetime(2026, 9, 2, 19, 19, 59, tzinfo=UTC),
            finished_at=datetime(2026, 9, 2, 19, 20, 0, tzinfo=UTC),
            ports=ports,
            events=events,
        )

        mock_svc = MagicMock()
        mock_svc.get_scan_details = AsyncMock(return_value=details)
        mock_svc_cls.return_value = mock_svc

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__.return_value = AsyncMock()
        mock_get_session.return_value = mock_session_ctx

        code = await run_history(None, 42, 10)
        assert code == 0
        captured = capsys.readouterr()

        # Check details
        assert "Scan: 42" in captured.out
        assert "Status: AVAILABLE" in captured.out
        assert "Response time: 1.2 ms" in captured.out

        # Check ports
        assert "22       CLOSED       0.8 ms" in captured.out
        assert "80       OPEN         1.0 ms" in captured.out
        assert "443      OPEN         1.2 ms" in captured.out

        # Check events
        assert "PORT_OPENED" in captured.out
        assert "Port: 443" in captured.out
        assert "CLOSED -> OPEN" in captured.out
        assert "HOST_BECAME_AVAILABLE" in captured.out
        assert "UNAVAILABLE -> AVAILABLE" in captured.out


class TestMainHistoryParser:
    @patch("sys.argv", ["netsentinel", "history", "127.0.0.1"])
    @patch("app.cli.run_history", new_callable=AsyncMock)
    def test_main_history_default(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = 0
        code = main()
        assert code == 0
        mock_run.assert_called_once_with("127.0.0.1", None, 10)

    @patch("sys.argv", ["netsentinel", "history", "127.0.0.1", "--limit", "5"])
    @patch("app.cli.run_history", new_callable=AsyncMock)
    def test_main_history_limit(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = 0
        code = main()
        assert code == 0
        mock_run.assert_called_once_with("127.0.0.1", None, 5)

    @patch("sys.argv", ["netsentinel", "history", "--scan", "42"])
    @patch("app.cli.run_history", new_callable=AsyncMock)
    def test_main_history_scan(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = 0
        code = main()
        assert code == 0
        mock_run.assert_called_once_with(None, 42, 10)
