"""Unit tests for host availability checking."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.monitoring.availability import HostAvailabilityResult, HostStatus, check_host_availability
from app.monitoring.port_scanner import PortScanResult
from app.monitoring.target import NetworkTarget
from app.monitoring.tcp_probe import PortStatus, TcpProbeResult

_LOOPBACK = NetworkTarget.parse("127.0.0.1")


async def _close_immediately(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Helper that closes the connection immediately, simulating a closed or reset port."""
    writer.close()
    await writer.wait_closed()


class TestAvailabilityWithRealSockets:
    """Test availability logic against real local sockets."""

    async def test_available_via_open_port(self) -> None:
        """A host with an open port should be AVAILABLE."""
        # Create a local server
        server = await asyncio.start_server(_close_immediately, host="127.0.0.1", port=0)
        port = server.sockets[0].getsockname()[1]
        
        try:
            result = await check_host_availability(_LOOPBACK, [port])
            assert result.status == HostStatus.AVAILABLE
            assert result.response_time_ms >= 0.0
            assert result.response_time_ms <= result.scan_result.duration_ms
        finally:
            server.close()
            await server.wait_closed()

    async def test_available_via_closed_port(self) -> None:
        """A host that explicitly rejects a connection (CLOSED) is still AVAILABLE."""
        # Port 0 on Windows/Linux generally cannot be connected to, returning ConnectionRefused
        # If the OS blocks it, we might get timeout, so let's mock the scanner behavior for certainty
        # or bind and close a port to guarantee it's closed, but OS behavior varies.
        # We will test the closed port logic via mocks in the next suite to guarantee determinism.
        pass


class TestAvailabilityWithMocks:
    """Test availability logic using mocks for deterministic scenarios."""

    @patch("app.monitoring.availability.scan_ports", new_callable=AsyncMock)
    async def test_available_via_closed_port_mock(self, mock_scan: AsyncMock) -> None:
        """A closed port means the host responded (e.g. RST packet), so it's AVAILABLE."""
        mock_scan.return_value = PortScanResult(
            target=_LOOPBACK,
            started_at=None,  # type: ignore
            finished_at=None,  # type: ignore
            duration_ms=50.0,
            ports=(TcpProbeResult(_LOOPBACK, 80, PortStatus.CLOSED, 10.0),),
        )
        
        result = await check_host_availability(_LOOPBACK, [80])
        assert result.status == HostStatus.AVAILABLE
        assert result.response_time_ms == 10.0

    @patch("app.monitoring.availability.scan_ports", new_callable=AsyncMock)
    async def test_unavailable_via_timeout(self, mock_scan: AsyncMock) -> None:
        """If all ports timeout, there is no evidence the host exists."""
        mock_scan.return_value = PortScanResult(
            target=_LOOPBACK,
            started_at=None,  # type: ignore
            finished_at=None,  # type: ignore
            duration_ms=1000.0,
            ports=(TcpProbeResult(_LOOPBACK, 80, PortStatus.TIMEOUT, 1000.0),),
        )
        
        result = await check_host_availability(_LOOPBACK, [80])
        assert result.status == HostStatus.UNAVAILABLE
        assert result.response_time_ms == 1000.0

    @patch("app.monitoring.availability.scan_ports", new_callable=AsyncMock)
    async def test_unavailable_via_unreachable(self, mock_scan: AsyncMock) -> None:
        """If all ports are unreachable (e.g. no route to host), it's UNAVAILABLE."""
        mock_scan.return_value = PortScanResult(
            target=_LOOPBACK,
            started_at=None,  # type: ignore
            finished_at=None,  # type: ignore
            duration_ms=2.0,
            ports=(TcpProbeResult(_LOOPBACK, 80, PortStatus.UNREACHABLE, 2.0),),
        )
        
        result = await check_host_availability(_LOOPBACK, [80])
        assert result.status == HostStatus.UNAVAILABLE
        assert result.response_time_ms == 2.0

    @patch("app.monitoring.availability.scan_ports", new_callable=AsyncMock)
    async def test_mixed_results_yields_available(self, mock_scan: AsyncMock) -> None:
        """If at least one port responds, the host is AVAILABLE."""
        mock_scan.return_value = PortScanResult(
            target=_LOOPBACK,
            started_at=None,  # type: ignore
            finished_at=None,  # type: ignore
            duration_ms=1000.0,
            ports=(
                TcpProbeResult(_LOOPBACK, 22, PortStatus.TIMEOUT, 1000.0),
                TcpProbeResult(_LOOPBACK, 80, PortStatus.CLOSED, 15.0),
                TcpProbeResult(_LOOPBACK, 443, PortStatus.UNREACHABLE, 2.0),
            ),
        )
        
        result = await check_host_availability(_LOOPBACK, [22, 80, 443])
        assert result.status == HostStatus.AVAILABLE
        # Latency should be the response time of the port that actually answered
        assert result.response_time_ms == 15.0

    async def test_empty_ports_list(self) -> None:
        """If no ports are provided, it's UNAVAILABLE immediately."""
        result = await check_host_availability(_LOOPBACK, [])
        assert result.status == HostStatus.UNAVAILABLE
        assert result.response_time_ms == 0.0
        assert len(result.scan_result.ports) == 0
