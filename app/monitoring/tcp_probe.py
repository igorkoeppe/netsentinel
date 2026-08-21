"""Single-port TCP probe.

Responsibilities:
- Attempt a TCP connection to one host + port.
- Return a structured result (status + duration).
- Guarantee socket cleanup in all code paths.

This module does NOT:
- scan multiple ports;
- manage concurrency;
- perform DNS resolution explicitly;
- depend on any external tool.
"""

import asyncio
import time
from dataclasses import dataclass
from enum import StrEnum

from app.monitoring.target import NetworkTarget

# Valid TCP port range (RFC 793).
_PORT_MIN: int = 1
_PORT_MAX: int = 65535


class PortStatus(StrEnum):
    """Outcome of a single TCP probe attempt."""

    OPEN = "open"
    CLOSED = "closed"
    TIMEOUT = "timeout"
    UNREACHABLE = "unreachable"


class InvalidPortError(ValueError):
    """Raised when a port number is outside the valid TCP range."""

    def __init__(self, port: int) -> None:
        self.port = port
        super().__init__(
            f"Invalid port {port}: must be an integer between "
            f"{_PORT_MIN} and {_PORT_MAX}"
        )


@dataclass(frozen=True)
class TcpProbeResult:
    """Result of a single TCP probe.

    Attributes:
        target:      The validated network target that was probed.
        port:        The TCP port number that was probed.
        status:      Outcome of the attempt (:class:`PortStatus`).
        duration_ms: Approximate time spent on the attempt, in milliseconds.
    """

    target: NetworkTarget
    port: int
    status: PortStatus
    duration_ms: float


def _validate_port(port: int) -> None:
    """Raise :class:`InvalidPortError` if *port* is outside the valid TCP range."""
    if not isinstance(port, int) or isinstance(port, bool):
        raise TypeError(f"port must be an int, got {type(port).__name__!r}")
    if port < _PORT_MIN or port > _PORT_MAX:
        raise InvalidPortError(port)


async def probe_tcp_port(
    target: NetworkTarget,
    port: int,
    timeout: float,
) -> TcpProbeResult:
    """Probe a single TCP port on *target* and return a structured result.

    The connection attempt is bounded by *timeout* seconds.
    The writer is always closed, even when an error occurs.

    Args:
        target:  A validated :class:`~app.monitoring.target.NetworkTarget`.
        port:    TCP port to probe (1–65535).
        timeout: Maximum time in seconds to wait for a connection.

    Returns:
        A :class:`TcpProbeResult` describing the outcome.

    Raises:
        TypeError:        If *port* is not an ``int``.
        InvalidPortError: If *port* is outside the valid range.
    """
    _validate_port(port)

    start = time.perf_counter()
    status = await _attempt_connection(target.value, port, timeout)
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    return TcpProbeResult(
        target=target,
        port=port,
        status=status,
        duration_ms=round(elapsed_ms, 3),
    )


async def _attempt_connection(host: str, port: int, timeout: float) -> PortStatus:
    """Try to open a TCP connection and return the appropriate :class:`PortStatus`.

    The writer is always closed before this coroutine returns.
    """
    writer: asyncio.StreamWriter | None = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        return PortStatus.OPEN

    except TimeoutError:
        return PortStatus.TIMEOUT

    except ConnectionRefusedError:
        return PortStatus.CLOSED

    except OSError:
        # Covers unreachable hosts, DNS failures, network errors, etc.
        return PortStatus.UNREACHABLE

    finally:
        if writer is not None:
            try:
                writer.close()
                await writer.wait_closed()
            except OSError:
                # Writer may already be in a broken state; ignore close errors.
                pass
