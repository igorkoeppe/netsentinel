from datetime import UTC, datetime

import pytest

from app.detection.alerts import AlertType, SecurityAlert, Severity
from app.detection.engine import MonitoringEvent, MonitoringEventType
from app.monitoring.target import NetworkTarget
from app.repositories.alert import AlertRepository
from app.repositories.host import HostRepository
from app.repositories.monitoring_event import MonitoringEventRepository
from app.repositories.scan import PortResultInput, ScanRepository
from app.services.history import HistoryService

UTC = UTC


@pytest.fixture
def host_repo(pg_session):
    return HostRepository(pg_session)


@pytest.fixture
def scan_repo(pg_session):
    return ScanRepository(pg_session)


@pytest.fixture
def event_repo(pg_session):
    return MonitoringEventRepository(pg_session)


@pytest.fixture
def alert_repo(pg_session):
    return AlertRepository(pg_session)


@pytest.fixture
def service(pg_session):
    return HistoryService(pg_session)


@pytest.mark.integration
class TestHistoryServiceIntegration:
    async def test_get_host_history_not_found(self, service):
        """Caso 1 — host inexistente"""
        result = await service.get_host_history("10.0.0.99")
        assert result is None

    async def test_get_host_history_no_scans(self, service, host_repo, pg_session):
        """Caso 2 — host sem scans"""
        await host_repo.create(address="10.0.0.1", name="router")
        await pg_session.commit()

        result = await service.get_host_history("10.0.0.1")
        assert result is not None
        assert result.address == "10.0.0.1"
        assert result.scans == []

    async def test_get_host_history_multiple_scans_and_limit(
        self, service, host_repo, scan_repo, pg_session
    ):
        """Caso 3 e 4 — múltiplos scans e limit"""
        host = await host_repo.create(address="10.0.0.2")
        await pg_session.flush()

        # Insert 3 scans at different times
        times = [
            datetime(2023, 1, 1, 10, 0, 0, tzinfo=UTC),
            datetime(2023, 1, 1, 11, 0, 0, tzinfo=UTC),
            datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC),
        ]

        for t in times:
            await scan_repo.create(
                host_id=host.id,
                status="available",
                response_time_ms=1.0,
                started_at=t,
                finished_at=t,
            )

        await pg_session.commit()

        # All 3 scans
        result_all = await service.get_host_history("10.0.0.2")
        assert result_all is not None
        assert len(result_all.scans) == 3
        # Should be ordered DESC by timestamp
        assert result_all.scans[0].timestamp == times[2]
        assert result_all.scans[1].timestamp == times[1]
        assert result_all.scans[2].timestamp == times[0]

        # Limit to 2
        result_limited = await service.get_host_history("10.0.0.2", limit=2)
        assert result_limited is not None
        assert len(result_limited.scans) == 2
        assert result_limited.scans[0].timestamp == times[2]
        assert result_limited.scans[1].timestamp == times[1]

    async def test_get_scan_details(
        self, service, host_repo, scan_repo, event_repo, pg_session
    ):
        """Caso 5 — scan details com ports e events"""
        host = await host_repo.create(address="10.0.0.3")
        await pg_session.flush()

        scan = await scan_repo.create(
            host_id=host.id,
            status="available",
            response_time_ms=1.5,
            started_at=datetime(2023, 1, 1, 10, 0, tzinfo=UTC),
            finished_at=datetime(2023, 1, 1, 10, 1, tzinfo=UTC),
        )
        await pg_session.flush()

        # 3 port results
        await scan_repo.add_port_results(
            scan.id,
            [
                PortResultInput(port=80, status="open", response_time_ms=2.0),
                PortResultInput(port=443, status="closed", response_time_ms=None),
                PortResultInput(port=8080, status="timeout", response_time_ms=None),
            ],
        )

        # 2 events
        target = NetworkTarget.parse("10.0.0.3")
        await event_repo.create(
            host_id=host.id,
            scan_id=scan.id,
            event=MonitoringEvent(
                event_type=MonitoringEventType.PORT_OPENED,
                target=target,
                timestamp=datetime(2023, 1, 1, 10, 0, 1, tzinfo=UTC),
                port=80,
                previous_state="closed",
                current_state="open",
            ),
        )
        await event_repo.create(
            host_id=host.id,
            scan_id=scan.id,
            event=MonitoringEvent(
                event_type=MonitoringEventType.HOST_BECAME_AVAILABLE,
                target=target,
                timestamp=datetime(2023, 1, 1, 10, 0, 2, tzinfo=UTC),
                port=None,
                previous_state="unavailable",
                current_state="available",
            ),
        )
        await pg_session.commit()

        details = await service.get_scan_details(scan.id)
        assert details is not None
        assert details.scan_id == scan.id
        assert details.status == "available"

        # Validate ports
        assert len(details.ports) == 3
        # Should be ordered by port number ascending
        assert details.ports[0].port == 80
        assert details.ports[1].port == 443
        assert details.ports[2].port == 8080

        # Validate events
        assert len(details.events) == 2
        # Should be ordered by insertion order (ID ascending)
        assert details.events[0].event_type == "port_opened"
        assert details.events[0].port == 80
        assert details.events[1].event_type == "host_became_available"
        assert details.events[1].port is None

    async def test_get_scan_details_not_found(self, service):
        """Caso 6 — scan inexistente"""
        result = await service.get_scan_details(999999)
        assert result is None

    async def test_multiple_hosts_isolation(
        self, service, host_repo, scan_repo, pg_session
    ):
        """Caso 7 — múltiplos hosts (dados não vazam)"""
        host_a = await host_repo.create(address="10.0.0.10")
        host_b = await host_repo.create(address="10.0.0.20")
        await pg_session.flush()

        t = datetime(2023, 1, 1, 10, 0, tzinfo=UTC)
        await scan_repo.create(
            host_id=host_a.id,
            status="available",
            response_time_ms=1.0,
            started_at=t,
            finished_at=t,
        )
        await scan_repo.create(
            host_id=host_a.id,
            status="available",
            response_time_ms=1.0,
            started_at=t,
            finished_at=t,
        )

        await scan_repo.create(
            host_id=host_b.id,
            status="available",
            response_time_ms=1.0,
            started_at=t,
            finished_at=t,
        )

        await pg_session.commit()

        history_a = await service.get_host_history("10.0.0.10")
        history_b = await service.get_host_history("10.0.0.20")

        assert history_a is not None and len(history_a.scans) == 2
        assert history_b is not None and len(history_b.scans) == 1

    async def test_get_scan_details_with_alerts(
        self, service, host_repo, scan_repo, event_repo, alert_repo, pg_session
    ):
        """Scan details includes correlated security alerts."""
        host = await host_repo.create(address="10.0.0.4")
        await pg_session.flush()

        scan = await scan_repo.create(
            host_id=host.id,
            status="available",
            response_time_ms=1.2,
            started_at=datetime(2023, 1, 1, 10, 0, tzinfo=UTC),
            finished_at=datetime(2023, 1, 1, 10, 1, tzinfo=UTC),
        )
        await pg_session.flush()

        target = NetworkTarget.parse("10.0.0.4")
        event = await event_repo.create(
            host_id=host.id,
            scan_id=scan.id,
            event=MonitoringEvent(
                event_type=MonitoringEventType.PORT_OPENED,
                target=target,
                timestamp=datetime(2023, 1, 1, 10, 0, 1, tzinfo=UTC),
                port=443,
                previous_state="closed",
                current_state="open",
            ),
        )

        alert = SecurityAlert(
            alert_type=AlertType.NEW_OPEN_PORT,
            severity=Severity.HIGH,
            target=target,
            timestamp=datetime(2023, 1, 1, 10, 0, 1, tzinfo=UTC),
            message="TCP port 443 is newly open.",
            port=443,
            source_event_type="port_opened",
        )
        await alert_repo.create(
            host_id=host.id,
            scan_id=scan.id,
            monitoring_event_id=event.id,
            alert=alert,
        )
        await pg_session.commit()

        details = await service.get_scan_details(scan.id)
        assert details is not None
        assert len(details.alerts) == 1
        a = details.alerts[0]
        assert a.alert_type == "new_open_port"
        assert a.severity == "high"
        assert a.port == 443
        assert a.message == "TCP port 443 is newly open."
        assert a.monitoring_event_id == event.id

    async def test_get_host_history_with_alert_counts(
        self, service, host_repo, scan_repo, alert_repo, pg_session
    ):
        """Host history correctly counts alerts per scan without N+1."""
        host = await host_repo.create(address="10.0.0.5")
        await pg_session.flush()

        t1 = datetime(2023, 1, 1, 10, 0, tzinfo=UTC)
        t2 = datetime(2023, 1, 1, 11, 0, tzinfo=UTC)

        scan1 = await scan_repo.create(
            host_id=host.id,
            status="available",
            response_time_ms=1.0,
            started_at=t1,
            finished_at=t1,
        )
        scan2 = await scan_repo.create(
            host_id=host.id,
            status="available",
            response_time_ms=1.0,
            started_at=t2,
            finished_at=t2,
        )
        await pg_session.flush()

        target = NetworkTarget.parse("10.0.0.5")
        # 2 alerts on scan2, 0 on scan1
        alert1 = SecurityAlert(
            alert_type=AlertType.NEW_OPEN_PORT,
            severity=Severity.HIGH,
            target=target,
            timestamp=t2,
            message="Port 80 open",
            port=80,
            source_event_type="port_opened",
        )
        alert2 = SecurityAlert(
            alert_type=AlertType.NEW_OPEN_PORT,
            severity=Severity.HIGH,
            target=target,
            timestamp=t2,
            message="Port 443 open",
            port=443,
            source_event_type="port_opened",
        )
        await alert_repo.create(
            host_id=host.id, scan_id=scan2.id, monitoring_event_id=None, alert=alert1
        )
        await alert_repo.create(
            host_id=host.id, scan_id=scan2.id, monitoring_event_id=None, alert=alert2
        )
        await pg_session.commit()

        history = await service.get_host_history("10.0.0.5")
        assert history is not None
        assert len(history.scans) == 2
        # scans ordered DESC by timestamp: scan2 (t2) first, then scan1 (t1)
        assert history.scans[0].scan_id == scan2.id
        assert history.scans[0].alert_count == 2
        assert history.scans[1].scan_id == scan1.id
        assert history.scans[1].alert_count == 0
