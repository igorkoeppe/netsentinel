"""Unit tests for app.monitoring.tcp_probe.

All tests are offline and deterministic.
Real local TCP servers are used instead of mocks wherever practical.
"""

import asyncio

import pytest

from app.monitoring.target import NetworkTarget
from app.monitoring.tcp_probe import (
    InvalidPortError,
    PortStatus,
    TcpProbeResult,
    probe_tcp_port,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LOOPBACK = NetworkTarget.parse("127.0.0.1")
_TIMEOUT = 1.0  # generous but bounded


async def _start_echo_server() -> tuple[asyncio.Server, int]:
    """Start a TCP server on a random loopback port and return (server, port)."""

    async def _noop_handler(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(_noop_handler, host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    return server, port


async def _free_port() -> int:
    """Return a port that has no active listener at the time of calling."""
    # Bind to get an OS-assigned port, then immediately release it.
    server = await asyncio.start_server(lambda r, w: None, host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()
    return port


# ---------------------------------------------------------------------------
# OPEN
# ---------------------------------------------------------------------------


class TestOpenPort:
    async def test_open_port_returns_open_status(self) -> None:
        server, port = await _start_echo_server()
        async with server:
            result = await probe_tcp_port(_LOOPBACK, port, timeout=_TIMEOUT)
        assert result.status == PortStatus.OPEN

    async def test_open_port_target_preserved(self) -> None:
        server, port = await _start_echo_server()
        async with server:
            result = await probe_tcp_port(_LOOPBACK, port, timeout=_TIMEOUT)
        assert result.target == _LOOPBACK

    async def test_open_port_number_preserved(self) -> None:
        server, port = await _start_echo_server()
        async with server:
            result = await probe_tcp_port(_LOOPBACK, port, timeout=_TIMEOUT)
        assert result.port == port

    async def test_open_port_duration_is_non_negative(self) -> None:
        server, port = await _start_echo_server()
        async with server:
            result = await probe_tcp_port(_LOOPBACK, port, timeout=_TIMEOUT)
        assert result.duration_ms >= 0.0

    async def test_open_port_duration_is_float(self) -> None:
        server, port = await _start_echo_server()
        async with server:
            result = await probe_tcp_port(_LOOPBACK, port, timeout=_TIMEOUT)
        assert isinstance(result.duration_ms, float)


# ---------------------------------------------------------------------------
# CLOSED
# ---------------------------------------------------------------------------


class TestClosedPort:
    async def test_closed_port_returns_closed_or_unreachable(self) -> None:
        port = await _free_port()
        result = await probe_tcp_port(_LOOPBACK, port, timeout=_TIMEOUT)
        # Windows firewall may drop the packet (TIMEOUT) or refuse it (CLOSED).
        # Both outcomes indicate the port is not open — either is acceptable.
        not_open = {PortStatus.CLOSED, PortStatus.TIMEOUT, PortStatus.UNREACHABLE}
        assert result.status in not_open

    async def test_closed_port_target_preserved(self) -> None:
        port = await _free_port()
        result = await probe_tcp_port(_LOOPBACK, port, timeout=_TIMEOUT)
        assert result.target == _LOOPBACK

    async def test_closed_port_duration_is_non_negative(self) -> None:
        port = await _free_port()
        result = await probe_tcp_port(_LOOPBACK, port, timeout=_TIMEOUT)
        assert result.duration_ms >= 0.0


# ---------------------------------------------------------------------------
# TIMEOUT
# ---------------------------------------------------------------------------


class TestTimeout:
    async def test_timeout_returns_timeout_status(self) -> None:
        # Use a non-routable address to force a real timeout.
        # RFC 5737 — 192.0.2.0/24 is reserved for documentation and must not route.
        target = NetworkTarget.parse("192.0.2.1")
        result = await probe_tcp_port(target, port=9, timeout=0.1)
        # On some systems, the OS immediately returns UNREACHABLE for non-routable
        # addresses; accept both outcomes as valid for a non-routable destination.
        assert result.status in {PortStatus.TIMEOUT, PortStatus.UNREACHABLE}

    async def test_short_timeout_is_respected(self) -> None:
        target = NetworkTarget.parse("192.0.2.1")
        result = await probe_tcp_port(target, port=9, timeout=0.1)
        # The probe must finish well within the test budget (2 seconds).
        assert result.duration_ms < 2_000


# ---------------------------------------------------------------------------
# Port validation
# ---------------------------------------------------------------------------


class TestPortValidation:
    async def test_port_zero_raises(self) -> None:
        with pytest.raises(InvalidPortError):
            await probe_tcp_port(_LOOPBACK, port=0, timeout=_TIMEOUT)

    async def test_negative_port_raises(self) -> None:
        with pytest.raises(InvalidPortError):
            await probe_tcp_port(_LOOPBACK, port=-1, timeout=_TIMEOUT)

    async def test_port_above_max_raises(self) -> None:
        with pytest.raises(InvalidPortError):
            await probe_tcp_port(_LOOPBACK, port=65536, timeout=_TIMEOUT)

    async def test_string_port_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            await probe_tcp_port(_LOOPBACK, port="80", timeout=_TIMEOUT)  # type: ignore[arg-type]

    async def test_none_port_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            await probe_tcp_port(_LOOPBACK, port=None, timeout=_TIMEOUT)  # type: ignore[arg-type]

    async def test_port_1_is_valid(self) -> None:
        # Port 1 is a valid TCP port; we only care about no validation error.
        result = await probe_tcp_port(_LOOPBACK, port=1, timeout=0.2)
        assert result.port == 1

    async def test_port_65535_is_valid(self) -> None:
        result = await probe_tcp_port(_LOOPBACK, port=65535, timeout=0.2)
        assert result.port == 65535


# ---------------------------------------------------------------------------
# Result structure
# ---------------------------------------------------------------------------


class TestResultStructure:
    async def test_result_is_frozen_dataclass(self) -> None:
        from dataclasses import FrozenInstanceError

        server, port = await _start_echo_server()
        async with server:
            result = await probe_tcp_port(_LOOPBACK, port, timeout=_TIMEOUT)
        with pytest.raises(FrozenInstanceError):
            result.status = PortStatus.CLOSED  # type: ignore[misc]

    async def test_result_type(self) -> None:
        server, port = await _start_echo_server()
        async with server:
            result = await probe_tcp_port(_LOOPBACK, port, timeout=_TIMEOUT)
        assert isinstance(result, TcpProbeResult)

    async def test_invalid_port_error_carries_port(self) -> None:
        with pytest.raises(InvalidPortError) as exc_info:
            await probe_tcp_port(_LOOPBACK, port=0, timeout=_TIMEOUT)
        assert exc_info.value.port == 0
