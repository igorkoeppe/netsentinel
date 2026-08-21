"""Unit tests for app.monitoring.port_scanner.

All tests are offline and deterministic.
Real local TCP servers are used for open-port cases.
The concurrency test uses a controlled mock to count simultaneous executions.
"""

import asyncio
from unittest.mock import patch

import pytest

from app.monitoring.port_scanner import PortScanResult, scan_ports
from app.monitoring.target import NetworkTarget
from app.monitoring.tcp_probe import PortStatus, TcpProbeResult

_LOOPBACK = NetworkTarget.parse("127.0.0.1")
_TIMEOUT = 1.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _start_server() -> tuple[asyncio.Server, int]:
    """Start a no-op TCP server on a random loopback port."""

    async def _close_immediately(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(_close_immediately, host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    return server, port


async def _free_port() -> int:
    """Return a port number that has no active listener."""
    server = await asyncio.start_server(lambda r, w: None, host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()
    return port


# ---------------------------------------------------------------------------
# Case 1 — multiple open ports
# ---------------------------------------------------------------------------


class TestMultipleOpenPorts:
    async def test_all_open_ports_detected(self) -> None:
        srv_a, port_a = await _start_server()
        srv_b, port_b = await _start_server()
        async with srv_a, srv_b:
            result = await scan_ports(_LOOPBACK, [port_a, port_b], timeout=_TIMEOUT)
        open_ports = {r.port for r in result.ports if r.status == PortStatus.OPEN}
        assert port_a in open_ports
        assert port_b in open_ports

    async def test_result_count_matches_port_count(self) -> None:
        srv_a, port_a = await _start_server()
        srv_b, port_b = await _start_server()
        async with srv_a, srv_b:
            result = await scan_ports(_LOOPBACK, [port_a, port_b], timeout=_TIMEOUT)
        assert len(result.ports) == 2

    async def test_result_target_preserved(self) -> None:
        srv, port = await _start_server()
        async with srv:
            result = await scan_ports(_LOOPBACK, [port], timeout=_TIMEOUT)
        assert result.target == _LOOPBACK


# ---------------------------------------------------------------------------
# Case 2 — mixed states (open + closed)
# ---------------------------------------------------------------------------


class TestMixedStates:
    async def test_open_and_closed_identified_separately(self) -> None:
        srv, open_port = await _start_server()
        closed_port = await _free_port()
        async with srv:
            result = await scan_ports(
                _LOOPBACK, [open_port, closed_port], timeout=_TIMEOUT
            )
        status_by_port = {r.port: r.status for r in result.ports}
        assert status_by_port[open_port] == PortStatus.OPEN
        # Windows may return TIMEOUT instead of CLOSED for a port with no listener.
        assert status_by_port[closed_port] in {
            PortStatus.CLOSED,
            PortStatus.TIMEOUT,
            PortStatus.UNREACHABLE,
        }

    async def test_all_ports_present_in_result(self) -> None:
        srv, open_port = await _start_server()
        closed_port = await _free_port()
        async with srv:
            result = await scan_ports(
                _LOOPBACK, [open_port, closed_port], timeout=_TIMEOUT
            )
        scanned_ports = {r.port for r in result.ports}
        assert open_port in scanned_ports
        assert closed_port in scanned_ports


# ---------------------------------------------------------------------------
# Case 3 — duplicate ports
# ---------------------------------------------------------------------------


class TestDuplicatePorts:
    async def test_duplicates_are_deduplicated(self) -> None:
        srv, port_a = await _start_server()
        srv_b, port_b = await _start_server()
        async with srv, srv_b:
            result = await scan_ports(
                _LOOPBACK, [port_a, port_a, port_b], timeout=_TIMEOUT
            )
        assert len(result.ports) == 2

    async def test_no_duplicate_port_numbers_in_result(self) -> None:
        srv, port = await _start_server()
        async with srv:
            result = await scan_ports(_LOOPBACK, [port, port], timeout=_TIMEOUT)
        port_numbers = [r.port for r in result.ports]
        assert len(port_numbers) == len(set(port_numbers))


# ---------------------------------------------------------------------------
# Case 4 — order
# ---------------------------------------------------------------------------


class TestResultOrder:
    async def test_results_sorted_by_port_ascending(self) -> None:
        srv_a, port_a = await _start_server()
        srv_b, port_b = await _start_server()
        srv_c, port_c = await _start_server()
        async with srv_a, srv_b, srv_c:
            # Pass ports in descending order; result must still be ascending.
            ports_desc = sorted([port_a, port_b, port_c], reverse=True)
            result = await scan_ports(_LOOPBACK, ports_desc, timeout=_TIMEOUT)
        result_ports = [r.port for r in result.ports]
        assert result_ports == sorted(result_ports)

    async def test_order_is_deterministic_across_runs(self) -> None:
        srv_a, port_a = await _start_server()
        srv_b, port_b = await _start_server()
        async with srv_a, srv_b:
            r1 = await scan_ports(_LOOPBACK, [port_b, port_a], timeout=_TIMEOUT)
            r2 = await scan_ports(_LOOPBACK, [port_a, port_b], timeout=_TIMEOUT)
        assert [r.port for r in r1.ports] == [r.port for r in r2.ports]


# ---------------------------------------------------------------------------
# Case 5 — empty list
# ---------------------------------------------------------------------------


class TestEmptyPortList:
    async def test_empty_list_returns_empty_ports(self) -> None:
        result = await scan_ports(_LOOPBACK, [], timeout=_TIMEOUT)
        assert result.ports == ()

    async def test_empty_list_returns_port_scan_result(self) -> None:
        result = await scan_ports(_LOOPBACK, [], timeout=_TIMEOUT)
        assert isinstance(result, PortScanResult)

    async def test_empty_list_duration_is_non_negative(self) -> None:
        result = await scan_ports(_LOOPBACK, [], timeout=_TIMEOUT)
        assert result.duration_ms >= 0.0


# ---------------------------------------------------------------------------
# Case 6 — concurrency limit
# ---------------------------------------------------------------------------


class TestConcurrencyLimit:
    async def test_concurrency_never_exceeds_limit(self) -> None:
        """Verify that at most *max_concurrency* probes run simultaneously.

        We patch probe_tcp_port with a controlled coroutine that tracks the
        peak number of concurrent executions without touching real sockets.
        """
        max_concurrency = 3
        num_ports = 10

        active: list[int] = [0]  # mutable cell for the counter
        peak: list[int] = [0]

        async def _fake_probe(
            target: NetworkTarget, port: int, timeout: float
        ) -> TcpProbeResult:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            await asyncio.sleep(0)  # yield to let other tasks start
            active[0] -= 1
            return TcpProbeResult(
                target=target,
                port=port,
                status=PortStatus.OPEN,
                duration_ms=0.0,
            )

        ports = list(range(8000, 8000 + num_ports))
        with patch(
            "app.monitoring.port_scanner.probe_tcp_port",
            side_effect=_fake_probe,
        ):
            await scan_ports(
                _LOOPBACK, ports, timeout=1.0, max_concurrency=max_concurrency
            )

        assert peak[0] <= max_concurrency


# ---------------------------------------------------------------------------
# PortScanResult structure
# ---------------------------------------------------------------------------


class TestPortScanResultStructure:
    async def test_result_has_started_at(self) -> None:
        result = await scan_ports(_LOOPBACK, [], timeout=_TIMEOUT)
        assert result.started_at is not None

    async def test_result_has_finished_at(self) -> None:
        result = await scan_ports(_LOOPBACK, [], timeout=_TIMEOUT)
        assert result.finished_at is not None

    async def test_finished_at_not_before_started_at(self) -> None:
        srv, port = await _start_server()
        async with srv:
            result = await scan_ports(_LOOPBACK, [port], timeout=_TIMEOUT)
        assert result.finished_at >= result.started_at

    async def test_result_is_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        result = await scan_ports(_LOOPBACK, [], timeout=_TIMEOUT)
        with pytest.raises(FrozenInstanceError):
            result.duration_ms = -1.0  # type: ignore[misc]
