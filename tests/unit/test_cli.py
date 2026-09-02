"""Unit tests for the CLI."""

import argparse
import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.cli import main, parse_interval, parse_ports, run_monitor, run_scan
from app.monitoring.availability import HostAvailabilityResult, HostStatus
from app.monitoring.port_scanner import PortScanResult
from app.monitoring.target import NetworkTarget
from app.monitoring.tcp_probe import PortStatus, TcpProbeResult


class TestParsePorts:
    def test_valid_ports(self) -> None:
        assert parse_ports("22,80,443") == [22, 80, 443]

    def test_with_spaces(self) -> None:
        assert parse_ports(" 22 , 80,  443 ") == [22, 80, 443]

    def test_duplicates_allowed_in_parser(self) -> None:
        # The parser returns the list, scanner will deduplicate
        assert parse_ports("80,80,443") == [80, 80, 443]

    def test_invalid_string(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError, match="Invalid TCP port: 'abc'"):
            parse_ports("80,abc,443")

    def test_out_of_range_zero(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError, match="Invalid TCP port: 0"):
            parse_ports("0")

    def test_out_of_range_high(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError, match="Invalid TCP port: 65536"):
            parse_ports("65536")

    def test_empty_string(self) -> None:
        with pytest.raises(
            argparse.ArgumentTypeError, match="Port list cannot be empty"
        ):
            parse_ports("")

    def test_empty_parts(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError, match="No valid ports provided"):
            parse_ports(",,,")


class TestParseInterval:
    def test_valid_interval(self) -> None:
        assert parse_interval("10") == 10
        assert parse_interval("1") == 1

    def test_invalid_string(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError, match="Invalid interval"):
            parse_interval("abc")

    def test_zero_interval(self) -> None:
        with pytest.raises(
            argparse.ArgumentTypeError, match="Interval must be strictly positive"
        ):
            parse_interval("0")

    def test_negative_interval(self) -> None:
        with pytest.raises(
            argparse.ArgumentTypeError, match="Interval must be strictly positive"
        ):
            parse_interval("-5")


class TestRunScan:
    async def test_invalid_target(self, capsys: pytest.CaptureFixture[str]) -> None:
        # URL is an invalid target
        code = await run_scan("http://example.com", [80])
        assert code == 2
        captured = capsys.readouterr()
        assert "error: invalid network target" in captured.err
        assert "URLs are not accepted" in captured.err

    @patch("app.cli.check_host_availability", new_callable=AsyncMock)
    async def test_valid_scan(
        self, mock_scan: AsyncMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = NetworkTarget.parse("127.0.0.1")
        mock_scan.return_value = HostAvailabilityResult(
            target=target,
            status=HostStatus.AVAILABLE,
            response_time_ms=1.5,
            scan_result=PortScanResult(
                target=target,
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
                duration_ms=10.0,
                ports=(
                    TcpProbeResult(target, 22, PortStatus.CLOSED, 1.5),
                    TcpProbeResult(target, 80, PortStatus.OPEN, 2.0),
                ),
            ),
        )

        code = await run_scan("127.0.0.1", [22, 80])
        assert code == 0

        captured = capsys.readouterr()
        # Verify output format
        assert "NetSentinel TCP Scan" in captured.out
        assert "Target: 127.0.0.1" in captured.out
        assert "Status: AVAILABLE" in captured.out
        assert "Response time: 1.5 ms" in captured.out
        assert "22       CLOSED       1.5 ms" in captured.out
        assert "80       OPEN         2.0 ms" in captured.out
        assert "2 ports scanned" in captured.out
        assert "1 open" in captured.out
        assert "1 closed" in captured.out

    @patch("app.cli.check_host_availability", new_callable=AsyncMock)
    async def test_unexpected_error(
        self, mock_scan: AsyncMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mock_scan.side_effect = RuntimeError("Something went wrong")

        code = await run_scan("127.0.0.1", [80])
        assert code == 1

        captured = capsys.readouterr()
        assert "error: unexpected failure: Something went wrong" in captured.err


class TestRunMonitor:
    async def test_invalid_target(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = await run_monitor("http://example.com", [80], 5, 2, False)
        assert code == 2
        captured = capsys.readouterr()
        assert "error: invalid network target" in captured.err

    @patch("app.cli.monitor_host")
    @patch("app.cli.detect_changes")
    async def test_single_snapshot(
        self,
        mock_detect: MagicMock,
        mock_monitor_host: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test 1 - primeiro snapshot (snapshot exibido; nenhum evento exibido)."""
        target = NetworkTarget.parse("127.0.0.1")
        snapshot = HostAvailabilityResult(
            target=target,
            status=HostStatus.AVAILABLE,
            response_time_ms=1.5,
            scan_result=PortScanResult(
                target=target,
                started_at=datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC),
                finished_at=datetime.now(UTC),
                duration_ms=10.0,
                ports=(TcpProbeResult(target, 80, PortStatus.OPEN, 2.0),),
            ),
        )

        async def mock_generator():
            yield snapshot

        mock_monitor_host.return_value = mock_generator()
        mock_detect.return_value = []

        code = await run_monitor("127.0.0.1", [80], 5, 1, False)
        assert code == 0

        captured = capsys.readouterr()
        assert "[12:00:00]" in captured.out
        assert "Changes detected:" not in captured.out
        assert "Monitoring session summary" in captured.out
        assert "Snapshots: 1" in captured.out
        assert "Events detected: 0" in captured.out
        assert "Duration:" in captured.out
        # detect_changes should not be called on the first snapshot
        mock_detect.assert_not_called()

    @patch("app.cli.monitor_host")
    @patch("app.cli.detect_changes")
    async def test_no_changes(
        self,
        mock_detect: MagicMock,
        mock_monitor_host: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test 2 - sem mudança (dois snapshots exibidos; nenhum bloco de eventos)."""
        target = NetworkTarget.parse("127.0.0.1")
        snapshot = HostAvailabilityResult(
            target=target,
            status=HostStatus.AVAILABLE,
            response_time_ms=1.5,
            scan_result=PortScanResult(
                target=target,
                started_at=datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC),
                finished_at=datetime.now(UTC),
                duration_ms=10.0,
                ports=(TcpProbeResult(target, 80, PortStatus.OPEN, 2.0),),
            ),
        )

        async def mock_generator():
            yield snapshot
            yield snapshot

        mock_monitor_host.return_value = mock_generator()
        mock_detect.return_value = []

        code = await run_monitor("127.0.0.1", [80], 5, 2, False)
        assert code == 0

        captured = capsys.readouterr()
        assert captured.out.count("[12:00:00]") == 2
        assert "Changes detected:" not in captured.out
        assert "Monitoring session summary" in captured.out
        assert "Snapshots: 2" in captured.out
        assert "Events detected: 0" in captured.out
        assert "Duration:" in captured.out

        # Test 8 - detector chamado corretamente
        mock_detect.assert_called_once_with(snapshot, snapshot)

    @patch("app.cli.monitor_host")
    @patch("app.cli.detect_changes")
    async def test_port_opened(
        self,
        mock_detect: MagicMock,
        mock_monitor_host: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test 3 - porta abriu."""
        target = NetworkTarget.parse("127.0.0.1")
        from app.detection.engine import MonitoringEvent, MonitoringEventType

        event = MonitoringEvent(
            event_type=MonitoringEventType.PORT_OPENED,
            target=target,
            timestamp=datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC),
            port=80,
            previous_state="closed",
            current_state="open",
        )

        snapshot = HostAvailabilityResult(
            target=target,
            status=HostStatus.AVAILABLE,
            response_time_ms=1.5,
            scan_result=PortScanResult(
                target=target,
                started_at=datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC),
                finished_at=datetime.now(UTC),
                duration_ms=10.0,
                ports=(TcpProbeResult(target, 80, PortStatus.OPEN, 2.0),),
            ),
        )

        async def mock_generator():
            yield snapshot
            yield snapshot

        mock_monitor_host.return_value = mock_generator()
        mock_detect.return_value = [event]

        await run_monitor("127.0.0.1", [80], 5, 2, False)

        captured = capsys.readouterr()
        assert "Changes detected:" in captured.out
        assert "PORT_OPENED" in captured.out
        assert "Port: 80" in captured.out
        assert "CLOSED -> OPEN" in captured.out
        assert "Monitoring session summary" in captured.out
        assert "Snapshots: 2" in captured.out
        assert "Events detected: 1" in captured.out
        assert "PORT_OPENED: 1" in captured.out
        assert "PORT_CLOSED: 0" in captured.out
        assert "Duration:" in captured.out

    @patch("app.cli.monitor_host")
    @patch("app.cli.detect_changes")
    async def test_port_closed(
        self,
        mock_detect: MagicMock,
        mock_monitor_host: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test 4 - porta fechou."""
        target = NetworkTarget.parse("127.0.0.1")
        from app.detection.engine import MonitoringEvent, MonitoringEventType

        event = MonitoringEvent(
            event_type=MonitoringEventType.PORT_CLOSED,
            target=target,
            timestamp=datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC),
            port=443,
            previous_state="open",
            current_state="closed",
        )

        snapshot = HostAvailabilityResult(
            target=target,
            status=HostStatus.AVAILABLE,
            response_time_ms=1.5,
            scan_result=PortScanResult(
                target=target,
                started_at=datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC),
                finished_at=datetime.now(UTC),
                duration_ms=10.0,
                ports=(TcpProbeResult(target, 443, PortStatus.CLOSED, 2.0),),
            ),
        )

        async def mock_generator():
            yield snapshot
            yield snapshot

        mock_monitor_host.return_value = mock_generator()
        mock_detect.return_value = [event]

        await run_monitor("127.0.0.1", [443], 5, 2, False)

        captured = capsys.readouterr()
        assert "Changes detected:" in captured.out
        assert "PORT_CLOSED" in captured.out
        assert "Port: 443" in captured.out
        assert "OPEN -> CLOSED" in captured.out
        assert "Monitoring session summary" in captured.out
        assert "Snapshots: 2" in captured.out
        assert "Events detected: 1" in captured.out
        assert "PORT_OPENED: 0" in captured.out
        assert "PORT_CLOSED: 1" in captured.out
        assert "Duration:" in captured.out

    @patch("app.cli.monitor_host")
    @patch("app.cli.detect_changes")
    async def test_host_unavailable_and_available(
        self,
        mock_detect: MagicMock,
        mock_monitor_host: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test 5 & 6 - host indisponível e voltou."""
        target = NetworkTarget.parse("127.0.0.1")
        from app.detection.engine import MonitoringEvent, MonitoringEventType

        event_unavail = MonitoringEvent(
            event_type=MonitoringEventType.HOST_BECAME_UNAVAILABLE,
            target=target,
            timestamp=datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC),
            previous_state="available",
            current_state="unavailable",
        )

        event_avail = MonitoringEvent(
            event_type=MonitoringEventType.HOST_BECAME_AVAILABLE,
            target=target,
            timestamp=datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC),
            previous_state="unavailable",
            current_state="available",
        )

        snapshot = HostAvailabilityResult(
            target=target,
            status=HostStatus.UNAVAILABLE,
            response_time_ms=1.5,
            scan_result=PortScanResult(
                target=target,
                started_at=datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC),
                finished_at=datetime.now(UTC),
                duration_ms=10.0,
                ports=(),
            ),
        )

        async def mock_generator():
            yield snapshot
            yield snapshot
            yield snapshot

        mock_monitor_host.return_value = mock_generator()
        mock_detect.side_effect = [[event_unavail], [event_avail]]

        await run_monitor("127.0.0.1", [80], 5, 3, False)

        captured = capsys.readouterr()
        assert "HOST_BECAME_UNAVAILABLE" in captured.out
        assert "AVAILABLE -> UNAVAILABLE" in captured.out
        assert "HOST_BECAME_AVAILABLE" in captured.out
        assert "UNAVAILABLE -> AVAILABLE" in captured.out
        assert "Monitoring session summary" in captured.out
        assert "Snapshots: 3" in captured.out
        assert "Events detected: 2" in captured.out
        assert "HOST_BECAME_UNAVAILABLE: 1" in captured.out
        assert "HOST_BECAME_AVAILABLE: 1" in captured.out

    @patch("app.cli.monitor_host")
    @patch("app.cli.detect_changes")
    async def test_multiple_events(
        self,
        mock_detect: MagicMock,
        mock_monitor_host: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test 7 - múltiplos eventos."""
        target = NetworkTarget.parse("127.0.0.1")
        from app.detection.engine import MonitoringEvent, MonitoringEventType

        event1 = MonitoringEvent(
            event_type=MonitoringEventType.PORT_OPENED,
            target=target,
            timestamp=datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC),
            port=80,
            previous_state="closed",
            current_state="open",
        )
        event2 = MonitoringEvent(
            event_type=MonitoringEventType.PORT_CLOSED,
            target=target,
            timestamp=datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC),
            port=443,
            previous_state="open",
            current_state="closed",
        )

        snapshot = HostAvailabilityResult(
            target=target,
            status=HostStatus.AVAILABLE,
            response_time_ms=1.5,
            scan_result=PortScanResult(
                target=target,
                started_at=datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC),
                finished_at=datetime.now(UTC),
                duration_ms=10.0,
                ports=(TcpProbeResult(target, 443, PortStatus.CLOSED, 2.0),),
            ),
        )

        async def mock_generator():
            yield snapshot
            yield snapshot

        mock_monitor_host.return_value = mock_generator()
        mock_detect.return_value = [event1, event2]

        await run_monitor("127.0.0.1", [80, 443], 5, 2, False)

        captured = capsys.readouterr()
        assert "PORT_OPENED" in captured.out
        assert "Port: 80" in captured.out
        assert "PORT_CLOSED" in captured.out
        assert "Port: 443" in captured.out
        assert "Monitoring session summary" in captured.out
        assert "Snapshots: 2" in captured.out
        assert "Events detected: 2" in captured.out
        assert "PORT_OPENED: 1" in captured.out
        assert "PORT_CLOSED: 1" in captured.out
        assert "Duration:" in captured.out

    @patch("app.cli.monitor_host")
    async def test_cancellation(
        self, mock_monitor_host: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        async def mock_generator():
            raise asyncio.CancelledError()
            yield  # type: ignore

        mock_monitor_host.return_value = mock_generator()

        code = await run_monitor("127.0.0.1", [80], 5, None, False)
        assert code == 0

        captured = capsys.readouterr()
        assert "Monitoring stopped." in captured.out
        assert "Monitoring session summary" in captured.out
        assert "Snapshots: 0" in captured.out
        assert "Events detected: 0" in captured.out
        assert "Duration:" in captured.out


class TestMain:
    @patch("sys.argv", ["netsentinel", "scan", "127.0.0.1", "--ports", "80,443"])
    @patch("app.cli.run_scan", new_callable=AsyncMock)
    def test_main_scan(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = 0
        code = main()
        assert code == 0
        mock_run.assert_called_once()

    @patch("sys.argv", ["netsentinel", "monitor", "127.0.0.1", "--ports", "80,443"])
    @patch("app.cli.run_monitor", new_callable=AsyncMock)
    def test_main_monitor(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = 0
        code = main()
        assert code == 0
        mock_run.assert_called_once()

    @patch("sys.argv", ["netsentinel"])
    def test_main_no_args(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 2
        captured = capsys.readouterr()
        assert "the following arguments are required: command" in captured.err

    @patch("sys.argv", ["netsentinel", "scan", "127.0.0.1"])
    def test_main_missing_ports(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 2
        captured = capsys.readouterr()
        assert "the following arguments are required: --ports" in captured.err
