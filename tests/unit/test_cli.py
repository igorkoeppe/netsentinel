"""Unit tests for the CLI."""

import argparse
import sys
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.cli import main, parse_ports, run_scan
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
        with pytest.raises(argparse.ArgumentTypeError, match="Port list cannot be empty"):
            parse_ports("")
            
    def test_empty_parts(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError, match="No valid ports provided"):
            parse_ports(",,,")


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
        )
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


class TestMain:
    @patch("sys.argv", ["netsentinel", "scan", "127.0.0.1", "--ports", "80,443"])
    @patch("app.cli.run_scan", new_callable=AsyncMock)
    def test_main_scan(self, mock_run: AsyncMock) -> None:
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
