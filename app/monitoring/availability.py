"""Host availability monitoring based on TCP probes."""

from dataclasses import dataclass
from enum import StrEnum

from app.core.config import settings
from app.monitoring.port_scanner import PortScanResult, scan_ports
from app.monitoring.target import NetworkTarget
from app.monitoring.tcp_probe import PortStatus


class HostStatus(StrEnum):
    """Represents the availability status of a host."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class HostAvailabilityResult:
    """Result of a host availability check."""

    target: NetworkTarget
    status: HostStatus
    response_time_ms: float
    scan_result: PortScanResult


async def check_host_availability(
    target: NetworkTarget,
    ports: list[int],
    timeout: float = settings.SCAN_TIMEOUT,
    max_concurrency: int = settings.SCAN_MAX_CONCURRENCY,
) -> HostAvailabilityResult:
    """
    Check if a host is available based on TCP port probes.

    A host is considered AVAILABLE if at least one port responds with OPEN or CLOSED.
    A CLOSED response means the host rejected the connection, which proves it is online.
    TIMEOUT and UNREACHABLE do not provide evidence of availability.

    If no ports are provided, returns UNAVAILABLE immediately as TCP requires ports.

    The response_time_ms is estimated using the smallest duration_ms among
    the responding ports (OPEN or CLOSED). If no port responds, the total
    scan duration is used as a fallback.
    """
    if not ports:
        # Cannot check availability via TCP without ports
        return HostAvailabilityResult(
            target=target,
            status=HostStatus.UNAVAILABLE,
            response_time_ms=0.0,
            scan_result=await scan_ports(target, ports, timeout, max_concurrency),
        )

    scan_result = await scan_ports(target, ports, timeout, max_concurrency)

    is_available = False
    responding_durations: list[float] = []

    for probe in scan_result.ports:
        if probe.status in (PortStatus.OPEN, PortStatus.CLOSED):
            is_available = True
            responding_durations.append(probe.duration_ms)

    status = HostStatus.AVAILABLE if is_available else HostStatus.UNAVAILABLE

    # Latency estimation: fastest response received (if any), otherwise total scan time
    if responding_durations:
        response_time_ms = min(responding_durations)
    else:
        response_time_ms = scan_result.duration_ms

    return HostAvailabilityResult(
        target=target,
        status=status,
        response_time_ms=response_time_ms,
        scan_result=scan_result,
    )
