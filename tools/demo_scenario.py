"""Exercise real local TCP probes, change detection and optional persistence.

Run from the repository root: python -m tools.demo_scenario [--persist]
"""

from __future__ import annotations

import argparse
import asyncio
import socket

from app.db.session import dispose_engine, get_db_session
from app.detection.alerts import AlertType, Severity
from app.detection.engine import detect_changes
from app.detection.rules import AlertPolicy, generate_alerts
from app.monitoring.availability import HostAvailabilityResult, check_host_availability
from app.monitoring.target import NetworkTarget
from app.monitoring.tcp_probe import PortStatus
from app.services.monitoring_persistence import MonitoringPersistenceService


async def close_connection(
    _reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass


async def run_scenario(ports: list[int], persist: bool) -> None:
    target = NetworkTarget.parse("127.0.0.1")
    policy = AlertPolicy(expected_tcp_ports=frozenset({ports[0]}))
    previous: HostAvailabilityResult | None = None
    servers: list[asyncio.Server] = []
    scan_ids: list[int] = []
    alert_ids: list[int] = []

    # Refuse to interact with ports already used by another local service.
    reservations: list[socket.socket] = []
    try:
        for port in ports:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            reservations.append(listener)
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind((target.value, port))
    finally:
        for listener in reservations:
            listener.close()

    async def snapshot(
        title: str,
        expected_ports: tuple[PortStatus, PortStatus],
        expected_alerts: list[tuple[AlertType, Severity]],
    ) -> None:
        nonlocal previous
        current = await check_host_availability(target, ports, timeout=5)
        observed_ports = tuple(probe.status for probe in current.scan_result.ports)
        if observed_ports != expected_ports:
            raise RuntimeError(
                f"{title}: portas retornaram {observed_ports}; "
                f"esperado {expected_ports}. Verifique se outro processo usa as portas."
            )
        events = detect_changes(previous, current)
        alerts = generate_alerts(events, policy)
        observed_alerts = [(alert.alert_type, alert.severity) for alert in alerts]
        if observed_alerts != expected_alerts:
            raise RuntimeError(f"{title}: alertas inesperados: {observed_alerts}")

        print(f"\n{title}")
        for probe in current.scan_result.ports:
            print(f"  {target.value}:{probe.port} = {probe.status.value.upper()}")
        for alert in alerts:
            print(
                f"  Alerta: {alert.alert_type.value.upper()} "
                f"| {alert.severity.value.upper()} | porta {alert.port}"
            )
        if not alerts:
            print("  Baseline registrado; nenhum alerta.")
        if persist:
            async with get_db_session() as session:
                cycle = await MonitoringPersistenceService(session).persist_cycle(
                    current, events, alerts
                )
                scan_ids.append(cycle.scan.id)
                alert_ids.extend(record.id for record in cycle.alerts)
                print(f"  Scan salvo: #{cycle.scan.id}")
        previous = current

    try:
        await snapshot(
            "1/4 - Baseline: duas portas fechadas",
            (PortStatus.CLOSED, PortStatus.CLOSED),
            [],
        )
        servers.append(
            await asyncio.start_server(close_connection, target.value, ports[0])
        )
        await snapshot(
            "2/4 - Servico autorizado iniciado",
            (PortStatus.OPEN, PortStatus.CLOSED),
            [(AlertType.EXPECTED_OPEN_PORT, Severity.INFO)],
        )
        servers.append(
            await asyncio.start_server(close_connection, target.value, ports[1])
        )
        await snapshot(
            "3/4 - Servico inesperado iniciado",
            (PortStatus.OPEN, PortStatus.OPEN),
            [(AlertType.UNEXPECTED_OPEN_PORT, Severity.HIGH)],
        )
        for server in servers:
            server.close()
        for server in servers:
            await server.wait_closed()
        await snapshot(
            "4/4 - Servicos encerrados",
            (PortStatus.CLOSED, PortStatus.CLOSED),
            [(AlertType.PORT_CLOSED, Severity.LOW)] * 2,
        )
        print("\nPASSOU: 4 scans e 4 alertas com tipos e severidades corretos.")
        if persist:
            print(f"Scans gravados: {scan_ids}")
            print(f"Alertas gravados: {alert_ids}")
            print("No dashboard, filtre o alvo 127.0.0.1 e confira esses IDs.")
    finally:
        for server in servers:
            server.close()
        for server in servers:
            await server.wait_closed()
        await dispose_engine()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cenario local de teste do NetSentinel"
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Gravar scans e alertas no banco configurado",
    )
    parser.add_argument(
        "--base-port",
        type=int,
        default=18080,
        help="Primeira das duas portas locais (padrao: 18080)",
    )
    args = parser.parse_args()
    if not 1 <= args.base_port < 65535:
        parser.error("--base-port deve estar entre 1 e 65534")
    try:
        asyncio.run(run_scenario([args.base_port, args.base_port + 1], args.persist))
    except (OSError, RuntimeError) as exc:
        print(f"FALHOU: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
