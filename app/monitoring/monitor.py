"""Host monitoring module."""

import asyncio
from collections.abc import AsyncGenerator

from app.core.config import settings
from app.monitoring.availability import HostAvailabilityResult, check_host_availability
from app.monitoring.target import NetworkTarget

# We alias HostAvailabilityResult to MonitoringSnapshot to clarify its role
# in continuous monitoring while avoiding code duplication.
MonitoringSnapshot = HostAvailabilityResult


async def monitor_host(
    target: NetworkTarget,
    ports: list[int],
    interval: int = settings.MONITOR_INTERVAL,
    timeout: float = settings.SCAN_TIMEOUT,
    max_concurrency: int = settings.SCAN_MAX_CONCURRENCY,
    max_iterations: int | None = None,
) -> AsyncGenerator[MonitoringSnapshot, None]:
    """Continuously monitor a host by executing scans at regular intervals.

    This function acts as an async generator, yielding a snapshot after each scan.
    The time taken by the scan itself adds to the interval drift.

    Args:
        target: The target to monitor.
        ports: The explicit list of ports to scan.
        interval: Interval in seconds to wait between scans. Must be strictly positive.
        timeout: Timeout per port connection.
        max_concurrency: Maximum number of simultaneous TCP probes.
        max_iterations: Maximum number of scans to perform. Useful for testing.
            If None, the monitor runs indefinitely.

    Raises:
        ValueError: If interval is <= 0.
        asyncio.CancelledError: If the monitor is cancelled.
    """
    if interval <= 0:
        raise ValueError(f"Interval must be strictly positive, got {interval}")

    iteration = 0
    while True:
        if max_iterations is not None and iteration >= max_iterations:
            break

        snapshot = await check_host_availability(
            target=target,
            ports=ports,
            timeout=timeout,
            max_concurrency=max_concurrency,
        )
        yield snapshot

        iteration += 1

        if max_iterations is not None and iteration >= max_iterations:
            break

        await asyncio.sleep(interval)
