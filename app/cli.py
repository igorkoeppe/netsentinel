"""Command Line Interface for NetSentinel."""

import argparse
import asyncio
import sys

from app.monitoring.availability import HostAvailabilityResult, check_host_availability
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
        print(f"{probe.port:<8} {probe.status.value.upper():<12} {probe.duration_ms:.1f} ms")
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


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="netsentinel", 
        description="NetSentinel - Network monitoring and security observability platform"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Scan TCP ports on a target")
    scan_parser.add_argument("target", help="The network target to scan (IP or hostname)")
    scan_parser.add_argument(
        "--ports", 
        required=True, 
        type=parse_ports,
        help="Comma-separated list of TCP ports to scan (e.g., 22,80,443)"
    )

    args = parser.parse_args()

    if args.command == "scan":
        return asyncio.run(run_scan(args.target, args.ports))
        
    return 2


if __name__ == "__main__":
    sys.exit(main())
