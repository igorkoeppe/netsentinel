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
from app.services.history import HostHistoryResult, ScanDetailsResult


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
            raise argparse.ArgumentTypeError(
                f"Invalid TCP port: '{port_part}'"
            ) from None

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
        ) from None
    if interval <= 0:
        raise argparse.ArgumentTypeError("Interval must be strictly positive.")
    return interval


def parse_limit(val: str) -> int:
    """Parse and validate the limit argument."""
    try:
        limit = int(val)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid limit: '{val}'. Must be an integer."
        ) from None
    if limit <= 0:
        raise argparse.ArgumentTypeError("Limit must be strictly positive.")
    return limit


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
            f"{probe.port:<8} {probe.status.value.upper():<12}"
            f" {probe.duration_ms:.1f} ms"
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
            f"{probe.port:<8} {probe.status.value.upper():<12}"
            f" {probe.duration_ms:.1f} ms"
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


def format_history(host_history: HostHistoryResult) -> None:
    """Format and print the host history summary."""
    print("\nNetSentinel History\n")
    print(f"Target: {host_history.address}\n")
    if not host_history.scans:
        print("No scans recorded.\n")
        return

    print(
        f"{'SCAN':<6} {'TIMESTAMP':<22} {'STATUS':<12} {'RESPONSE':<12} "
        f"{'PORTS':<7} {'EVENTS'}"
    )
    for scan in host_history.scans:
        timestamp_str = scan.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        response_str = (
            f"{scan.response_time_ms:.1f} ms"
            if scan.response_time_ms is not None
            else "-"
        )
        port_count_str = str(scan.port_count) if scan.port_count is not None else "-"
        event_count_str = str(scan.event_count) if scan.event_count is not None else "-"
        print(
            f"{scan.scan_id:<6} {timestamp_str:<22} {scan.status.upper():<12} "
            f"{response_str:<12} {port_count_str:<7} {event_count_str}"
        )
    print()


def format_scan_details(details: ScanDetailsResult) -> None:
    """Format and print the details of a specific scan."""
    print("\nNetSentinel Scan Details\n")
    print(f"Scan: {details.scan_id}")
    print(f"Status: {details.status.upper()}")
    resp_str = (
        f"{details.response_time_ms:.1f} ms"
        if details.response_time_ms is not None
        else "-"
    )
    print(f"Response time: {resp_str}")
    print(f"Started: {details.started_at.strftime('%Y-%m-%d %H:%M:%S')}")
    if details.finished_at:
        print(f"Finished: {details.finished_at.strftime('%Y-%m-%d %H:%M:%S')}")

    print("\nPorts\n")
    if not details.ports:
        print("none")
    else:
        print(f"{'PORT':<8} {'STATUS':<12} {'RESPONSE'}")
        for p in details.ports:
            p_resp = (
                f"{p.response_time_ms:.1f} ms"
                if p.response_time_ms is not None
                else "-"
            )
            print(f"{p.port:<8} {p.status.upper():<12} {p_resp}")

    print("\nEvents\n")
    if not details.events:
        print("none\n")
    else:
        for e in details.events:
            print(f"{e.event_type.upper()}")
            if e.port is not None:
                print(f"Port: {e.port}")
            if e.previous_state and e.current_state:
                print(f"{e.previous_state.upper()} -> {e.current_state.upper()}")
            print(f"Timestamp: {e.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n")


def format_session_summary(
    target: NetworkTarget,
    snapshot_count: int,
    events: list[MonitoringEvent],
    duration: float,
    persist: bool,
) -> None:
    """Format and print the final monitoring session summary."""
    print("\nMonitoring session summary\n")
    print(f"Target: {target.value}")
    if persist:
        print("Persistence: enabled")
    print(f"Snapshots: {snapshot_count}")
    print(f"Events detected: {len(events)}")
    if duration >= 0:
        print(f"Duration: {duration:.1f}s")

    print()
    counter = Counter(e.event_type for e in events)
    for event_type in MonitoringEventType:
        print(f"{event_type.name}: {counter[event_type]}")


async def run_monitor(
    target_str: str, ports: list[int], interval: int, count: int | None, persist: bool
) -> int:
    """Execute continuous monitoring and print snapshots."""
    if persist and not settings.DATABASE_URL:
        print(
            "error: DATABASE_URL is required when --persist is enabled", file=sys.stderr
        )
        return 1

    try:
        target = NetworkTarget.parse(target_str)
    except InvalidTargetError as e:
        print(f"error: invalid network target: {e.reason}", file=sys.stderr)
        return 2

    print("\nNetSentinel Monitor\n")
    print(f"Target: {target.value}")
    print(f"Interval: {interval}s")
    if persist:
        print("Persistence: enabled")

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
            events_to_persist: list[MonitoringEvent] = []
            if previous_snapshot is not None:
                events_to_persist = detect_changes(previous_snapshot, snapshot)
                if events_to_persist:
                    session_events.extend(events_to_persist)
                    format_monitoring_events(events_to_persist)
            previous_snapshot = snapshot

            if persist:
                # Lazy import to avoid loading DB code if not persisting
                from app.db.session import get_db_session, get_engine
                from app.services.monitoring_persistence import (
                    MonitoringPersistenceService,
                )

                try:
                    async with get_db_session() as session:
                        svc = MonitoringPersistenceService(session)
                        # The first snapshot yields [] events, but is persisted.
                        await svc.persist_cycle(snapshot, events_to_persist)
                except Exception as e:
                    print(
                        f"\nerror: failed to persist monitoring cycle: {e}",
                        file=sys.stderr,
                    )
                    return 1

    except (asyncio.CancelledError, KeyboardInterrupt):
        print("\nMonitoring stopped.")
    except Exception as e:
        print(f"\nerror: unexpected failure: {e}", file=sys.stderr)
        return 1
    finally:
        if persist:
            from app.db.session import get_engine

            engine = get_engine()
            await engine.dispose()

    duration = time.perf_counter() - start_time
    format_session_summary(target, snapshot_count, session_events, duration, persist)

    return 0


async def run_history(target_str: str | None, scan_id: int | None, limit: int) -> int:
    """Execute the history query."""
    if not settings.DATABASE_URL:
        print("error: DATABASE_URL is required for history queries", file=sys.stderr)
        return 1

    if not target_str and scan_id is None:
        print("error: must provide either TARGET or --scan", file=sys.stderr)
        return 2

    # Lazy import to avoid loading DB code if not running history
    from sqlalchemy.exc import OperationalError

    from app.db.session import get_db_session, get_engine
    from app.services.history import HistoryService

    engine = get_engine()

    try:
        if scan_id is not None:
            async with get_db_session() as session:
                svc = HistoryService(session)
                details = await svc.get_scan_details(scan_id)
                if not details:
                    print("\nScan not found.\n")
                    return 0
                format_scan_details(details)
                return 0
        else:
            try:
                # target_str is guaranteed not to be None here
                target = NetworkTarget.parse(target_str)  # type: ignore
            except InvalidTargetError as e:
                print(f"error: invalid network target: {e.reason}", file=sys.stderr)
                return 2

            async with get_db_session() as session:
                svc = HistoryService(session)
                host_history = await svc.get_host_history(target.value, limit=limit)

                if not host_history:
                    print(f"\nNo persisted history found for {target.value}.\n")
                    return 0

                format_history(host_history)
                return 0
    except OperationalError:
        print("error: could not connect to PostgreSQL database", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"error: unexpected failure: {e}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="netsentinel",
        description=(
            "NetSentinel - Network monitoring and security observability platform"
        ),
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
        help=(
            f"Interval in seconds between scans (default: {settings.MONITOR_INTERVAL})"
        ),
    )
    monitor_parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Limit the number of monitoring iterations (default: continuous)",
    )
    monitor_parser.add_argument(
        "--persist",
        action="store_true",
        help="Persist snapshots and events to the PostgreSQL database",
    )

    history_parser = subparsers.add_parser(
        "history", help="View persisted monitoring history"
    )
    history_parser.add_argument(
        "target",
        nargs="?",
        help="The network target to view history for (IP or hostname)",
    )
    history_parser.add_argument(
        "--scan",
        type=int,
        help="View details for a specific scan ID",
    )
    history_parser.add_argument(
        "--limit",
        type=parse_limit,
        default=10,
        help="Maximum number of scans to show (default: 10)",
    )

    args = parser.parse_args()

    if args.command == "scan":
        return asyncio.run(run_scan(args.target, args.ports))
    elif args.command == "monitor":
        try:
            return asyncio.run(
                run_monitor(
                    args.target, args.ports, args.interval, args.count, args.persist
                )
            )
        except KeyboardInterrupt:
            print("\nMonitoring stopped.")
            return 0
    elif args.command == "history":
        return asyncio.run(run_history(args.target, args.scan, args.limit))

    return 2


if __name__ == "__main__":
    sys.exit(main())
