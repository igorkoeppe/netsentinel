"""Command Line Interface for NetSentinel."""

import argparse
import asyncio
import sys
import time
from collections import Counter

from app.core.config import settings
from app.detection.engine import MonitoringEvent, MonitoringEventType, detect_changes
from app.monitoring.availability import HostAvailabilityResult, check_host_availability
from app.monitoring.monitor import monitor_host
from app.monitoring.target import InvalidTargetError, NetworkTarget


def parse_ports(ports_str: str) -> list[int]:
    """Parse a comma-separated string of ports into a list of integers."""
    ports = []
    if not ports_str.strip():
        raise argparse.ArgumentTypeError("Port list cannot be empty.")

    for port_part in ports_str.split(","):
        port_part = port_part.strip()
        if not port_part:
            continue
        try:
            port_num = int(port_part)
        except ValueError:
            raise argparse.ArgumentTypeError(f"Invalid TCP port: '{port_part}'")

        if port_num < 1 or port_num > 65535:
            raise argparse.ArgumentTypeError(f"Invalid TCP port: {port_num}")

        ports.append(port_num)

    if not ports:
        raise argparse.ArgumentTypeError("No valid ports provided.")

    return ports


def parse_interval(val: str) -> int:
    """Parse and validate the interval argument."""
    try:
        interval = int(val)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid interval: '{val}'. Must be an integer."
        )
    if interval <= 0:
        raise argparse.ArgumentTypeError("Interval must be strictly positive.")
    return interval


def format_results(result: HostAvailabilityResult) -> None:
    """Format and print the scan results to stdout."""
    print("\nNetSentinel TCP Scan\n")
    print(f"Target: {result.target.value}")
    print(f"Status: {result.status.value.upper()}")
    print(f"Response time: {result.response_time_ms:.1f} ms\n")

    # Header
    print(f"{'PORT':<8} {'STATUS':<12} {'TIME'}")

    open_count = 0
    closed_count = 0

    for probe in result.scan_result.ports:
        print(
            f"{probe.port:<8} {probe.status.value.upper():<12} {probe.duration_ms:.1f} ms"
        )
        if probe.status.value == "open":
            open_count += 1
        elif probe.status.value == "closed":
            closed_count += 1

    print(f"\n{len(result.scan_result.ports)} ports scanned")
    print(f"{open_count} open")
    print(f"{closed_count} closed")


async def run_scan(target_str: str, ports: list[int]) -> int:
    """Execute the port scan and print results."""
    try:
        target = NetworkTarget.parse(target_str)
    except InvalidTargetError as e:
        print(f"error: invalid network target: {e.reason}", file=sys.stderr)
        return 2

    try:
        result = await check_host_availability(target=target, ports=ports)
    except Exception as e:
        print(f"error: unexpected failure: {e}", file=sys.stderr)
        return 1

    format_results(result)
    return 0


def format_snapshot(snapshot: HostAvailabilityResult) -> None:
    """Format a single monitoring snapshot."""
    timestamp_str = snapshot.scan_result.started_at.strftime("%H:%M:%S")
    print(f"\n[{timestamp_str}]")
    print(f"Status: {snapshot.status.value.upper()}")
    print(f"Response time: {snapshot.response_time_ms:.1f} ms\n")
    print(f"{'PORT':<8} {'STATUS':<12} {'TIME'}")

    for probe in snapshot.scan_result.ports:
        print(
            f"{probe.port:<8} {probe.status.value.upper():<12} {probe.duration_ms:.1f} ms"
        )


def format_monitoring_events(events: list[MonitoringEvent]) -> None:
    """Format and print a list of monitoring events."""
    if not events:
        return

    print("\nChanges detected:\n")
    for event in events:
        timestamp_str = event.timestamp.strftime("%H:%M:%S")
        print(f"[{timestamp_str}] {event.event_type.value.upper()}")
        if event.port is not None:
            print(f"Port: {event.port}")
        if event.previous_state and event.current_state:
            print(f"{event.previous_state.upper()} -> {event.current_state.upper()}")
        print()


def format_session_summary(
    target: NetworkTarget,
    snapshot_count: int,
    events: list[MonitoringEvent],
    duration: float,
) -> None:
    """Format and print the final monitoring session summary."""
    print("\nMonitoring session summary\n")
    print(f"Target: {target.value}")
    print(f"Snapshots: {snapshot_count}")
    print(f"Events detected: {len(events)}")
    if duration >= 0:
        print(f"Duration: {duration:.1f}s")

    print()
    counter = Counter(e.event_type for e in events)
    for event_type in MonitoringEventType:
        print(f"{event_type.name}: {counter[event_type]}")


async def run_monitor(
    target_str: str, ports: list[int], interval: int, count: int | None
) -> int:
    """Execute continuous monitoring and print snapshots."""
    try:
        target = NetworkTarget.parse(target_str)
    except InvalidTargetError as e:
        print(f"error: invalid network target: {e.reason}", file=sys.stderr)
        return 2

    print("\nNetSentinel Monitor\n")
    print(f"Target: {target.value}")
    print(f"Interval: {interval}s")

    snapshot_count = 0
    session_events: list[MonitoringEvent] = []
    start_time = time.perf_counter()

    try:
        previous_snapshot: HostAvailabilityResult | None = None
        async for snapshot in monitor_host(
            target=target,
            ports=ports,
            interval=interval,
            max_iterations=count,
        ):
            snapshot_count += 1
            format_snapshot(snapshot)
            if previous_snapshot is not None:
                events = detect_changes(previous_snapshot, snapshot)
                if events:
                    session_events.extend(events)
                    format_monitoring_events(events)
            previous_snapshot = snapshot
    except (asyncio.CancelledError, KeyboardInterrupt):
        print("\nMonitoring stopped.")
    except Exception as e:
        print(f"\nerror: unexpected failure: {e}", file=sys.stderr)
        return 1

    duration = time.perf_counter() - start_time
    format_session_summary(target, snapshot_count, session_events, duration)

    return 0


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="netsentinel",
        description="NetSentinel - Network monitoring and security observability platform",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Scan TCP ports on a target")
    scan_parser.add_argument(
        "target", help="The network target to scan (IP or hostname)"
    )
    scan_parser.add_argument(
        "--ports",
        required=True,
        type=parse_ports,
        help="Comma-separated list of TCP ports to scan (e.g., 22,80,443)",
    )

    monitor_parser = subparsers.add_parser(
        "monitor", help="Continuously monitor TCP ports on a target"
    )
    monitor_parser.add_argument(
        "target", help="The network target to monitor (IP or hostname)"
    )
    monitor_parser.add_argument(
        "--ports",
        required=True,
        type=parse_ports,
        help="Comma-separated list of TCP ports to monitor",
    )
    monitor_parser.add_argument(
        "--interval",
        type=parse_interval,
        default=settings.MONITOR_INTERVAL,
        help=f"Interval in seconds between scans (default: {settings.MONITOR_INTERVAL})",
    )
    monitor_parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Limit the number of monitoring iterations (default: continuous)",
    )

    args = parser.parse_args()

    if args.command == "scan":
        return asyncio.run(run_scan(args.target, args.ports))
    elif args.command == "monitor":
        try:
            return asyncio.run(
                run_monitor(args.target, args.ports, args.interval, args.count)
            )
        except KeyboardInterrupt:
            print("\nMonitoring stopped.")
            return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
