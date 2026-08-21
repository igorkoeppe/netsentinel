"""TCP port scanner — scans multiple ports on a single target.

Responsibilities:
- Accept a target and an explicit list of ports.
- Deduplicate ports and execute probes concurrently.
- Limit concurrency with asyncio.Semaphore.
- Return results sorted numerically by port number.

This module does NOT:
- re-implement TCP connection logic (delegated to tcp_probe);
- scan IP ranges or subnets;
- perform host discovery;
- fingerprint services.
"""

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.config import settings
from app.monitoring.target import NetworkTarget
from app.monitoring.tcp_probe import TcpProbeResult, probe_tcp_port

# Common ports useful for a basic demonstration scan.
# This list is intentionally small and conservative.
# Users should always provide an explicit port list.
DEFAULT_PORTS: tuple[int, ...] = (22, 53, 80, 443, 3306, 5432, 6379, 8080)


@dataclass(frozen=True)
class PortScanResult:
    """Aggregated result of scanning multiple ports on a single target.

    Attributes:
        target:      The validated network target that was scanned.
        started_at:  UTC timestamp when the scan began.
        finished_at: UTC timestamp when the scan completed.
        duration_ms: Total elapsed time for the entire scan, in milliseconds.
        ports:       Individual probe results, sorted by port number.
    """

    target: NetworkTarget
    started_at: datetime
    finished_at: datetime
    duration_ms: float
    ports: tuple[TcpProbeResult, ...] = ()


async def scan_ports(
    target: NetworkTarget,
    ports: list[int],
    timeout: float = settings.SCAN_TIMEOUT,
    max_concurrency: int = settings.SCAN_MAX_CONCURRENCY,
) -> PortScanResult:
    """Scan multiple TCP ports on *target* concurrently.

    Duplicate ports are silently deduplicated before scanning.
    Results are always returned sorted by port number, regardless of
    the order in which they complete.

    Args:
        target:          A validated :class:`~app.monitoring.target.NetworkTarget`.
        ports:           Explicit list of TCP port numbers to scan (1–65535).
                         Duplicates are ignored; an empty list returns immediately.
        timeout:         Per-port connection timeout in seconds.
        max_concurrency: Maximum number of simultaneous TCP probes.

    Returns:
        A :class:`PortScanResult` with all individual probe results.

    Raises:
        TypeError:        If any port is not an ``int``.
        InvalidPortError: If any port is outside the valid range (validated
                          by the underlying probe on first execution).
        asyncio.CancelledError: Propagated if the task is cancelled.
    """
    # Deduplicate while preserving a consistent ordering for predictable behaviour.
    unique_ports = sorted(dict.fromkeys(ports))

    wall_start = time.perf_counter()
    started_at = datetime.now(UTC)

    probe_results = await _run_probes(target, unique_ports, timeout, max_concurrency)

    finished_at = datetime.now(UTC)
    duration_ms = round((time.perf_counter() - wall_start) * 1000.0, 3)

    # Sort by port number to guarantee a deterministic output order.
    sorted_results = tuple(sorted(probe_results, key=lambda r: r.port))

    return PortScanResult(
        target=target,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        ports=sorted_results,
    )


async def _run_probes(
    target: NetworkTarget,
    ports: list[int],
    timeout: float,
    max_concurrency: int,
) -> list[TcpProbeResult]:
    """Launch concurrent probes for all *ports*, respecting *max_concurrency*.

    asyncio.CancelledError is not caught — cancellation propagates to the caller.
    """
    if not ports:
        return []

    semaphore = asyncio.Semaphore(max_concurrency)

    async def _bounded_probe(port: int) -> TcpProbeResult:
        async with semaphore:
            return await probe_tcp_port(target, port, timeout)

    tasks = [asyncio.create_task(_bounded_probe(port)) for port in ports]

    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        # Cancel any tasks still running before re-raising.
        for task in tasks:
            task.cancel()
        # Allow pending cancellations to propagate.
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
