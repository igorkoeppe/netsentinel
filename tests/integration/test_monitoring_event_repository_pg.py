"""Integration tests for MonitoringEventRepository against a real PostgreSQL database.

These tests require ``TEST_DATABASE_URL`` to be set and are tagged with the
``integration`` marker so that they are excluded from the default ``pytest``
run::

    # Only unit tests (no database required):
    pytest

    # PostgreSQL integration tests (set TEST_DATABASE_URL first):
    #   pytest -m integration

Each test runs inside a transaction that is rolled back automatically by the
``pg_session`` fixture in ``conftest.py``, so tests are fully isolated.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.detection.engine import MonitoringEvent, MonitoringEventType
from app.monitoring.target import NetworkTarget
from app.repositories.host import HostRepository
from app.repositories.monitoring_event import MonitoringEventRepository
from app.repositories.scan import ScanRepository

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_TARGET = NetworkTarget.parse("10.0.0.1")


def _port_opened_event(port: int, *, timestamp: datetime = _NOW) -> MonitoringEvent:
    return MonitoringEvent(
        event_type=MonitoringEventType.PORT_OPENED,
        target=_TARGET,
        timestamp=timestamp,
        port=port,
        previous_state="closed",
        current_state="open",
    )


def _port_closed_event(port: int, *, timestamp: datetime = _NOW) -> MonitoringEvent:
    return MonitoringEvent(
        event_type=MonitoringEventType.PORT_CLOSED,
        target=_TARGET,
        timestamp=timestamp,
        port=port,
        previous_state="open",
        current_state="closed",
    )


def _host_available_event(*, timestamp: datetime = _NOW) -> MonitoringEvent:
    return MonitoringEvent(
        event_type=MonitoringEventType.HOST_BECAME_AVAILABLE,
        target=_TARGET,
        timestamp=timestamp,
        port=None,
        previous_state="unavailable",
        current_state="available",
    )


def _host_unavailable_event(*, timestamp: datetime = _NOW) -> MonitoringEvent:
    return MonitoringEvent(
        event_type=MonitoringEventType.HOST_BECAME_UNAVAILABLE,
        target=_TARGET,
        timestamp=timestamp,
        port=None,
        previous_state="available",
        current_state="unavailable",
    )


async def _make_host(host_repo: HostRepository, address: str) -> int:
    host = await host_repo.create(address=address)
    return host.id


async def _make_scan(
    scan_repo: ScanRepository,
    host_id: int,
    *,
    started_at: datetime = _NOW,
) -> int:
    scan = await scan_repo.create(
        host_id=host_id,
        status="available",
        response_time_ms=1.0,
        started_at=started_at,
        finished_at=None,
    )
    return scan.id


# ---------------------------------------------------------------------------
# create — PORT_OPENED
# ---------------------------------------------------------------------------


class TestCreatePortOpened:
    async def test_port_opened_fields(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        event_repo: MonitoringEventRepository,
        pg_session: AsyncSession,
    ) -> None:
        """PORT_OPENED record must store all fields correctly."""
        host_id = await _make_host(host_repo, "10.1.0.1")
        scan_id = await _make_scan(scan_repo, host_id)
        event = _port_opened_event(443)

        record = await event_repo.create(
            host_id=host_id,
            scan_id=scan_id,
            event=event,
        )
        record_id = record.id
        pg_session.expire_all()
        fetched = await event_repo.get_by_id(record_id)

        assert fetched is not None
        assert fetched.event_type == "port_opened"
        assert fetched.port == 443
        assert fetched.previous_state == "closed"
        assert fetched.current_state == "open"
        assert fetched.host_id == host_id
        assert fetched.scan_id == scan_id

    async def test_port_opened_id_is_int(
        self,
        host_repo: HostRepository,
        event_repo: MonitoringEventRepository,
    ) -> None:
        host_id = await _make_host(host_repo, "10.1.0.2")
        record = await event_repo.create(
            host_id=host_id, scan_id=None, event=_port_opened_event(80)
        )
        assert isinstance(record.id, int)
        assert record.id > 0


# ---------------------------------------------------------------------------
# create — PORT_CLOSED
# ---------------------------------------------------------------------------


class TestCreatePortClosed:
    async def test_port_closed_fields(
        self,
        host_repo: HostRepository,
        event_repo: MonitoringEventRepository,
        pg_session: AsyncSession,
    ) -> None:
        """PORT_CLOSED record must store all fields correctly."""
        host_id = await _make_host(host_repo, "10.2.0.1")
        event = _port_closed_event(22)

        record = await event_repo.create(host_id=host_id, scan_id=None, event=event)
        record_id = record.id
        pg_session.expire_all()
        fetched = await event_repo.get_by_id(record_id)

        assert fetched is not None
        assert fetched.event_type == "port_closed"
        assert fetched.port == 22
        assert fetched.previous_state == "open"
        assert fetched.current_state == "closed"


# ---------------------------------------------------------------------------
# create — HOST_BECAME_UNAVAILABLE (host event, port is None)
# ---------------------------------------------------------------------------


class TestCreateHostEvent:
    async def test_host_event_port_is_none(
        self,
        host_repo: HostRepository,
        event_repo: MonitoringEventRepository,
        pg_session: AsyncSession,
    ) -> None:
        """HOST_BECAME_UNAVAILABLE must store port=None."""
        host_id = await _make_host(host_repo, "10.3.0.1")
        event = _host_unavailable_event()

        record = await event_repo.create(host_id=host_id, scan_id=None, event=event)
        record_id = record.id
        pg_session.expire_all()
        fetched = await event_repo.get_by_id(record_id)

        assert fetched is not None
        assert fetched.event_type == "host_became_unavailable"
        assert fetched.port is None

    async def test_host_event_optional_fields_nullable(
        self,
        host_repo: HostRepository,
        event_repo: MonitoringEventRepository,
        pg_session: AsyncSession,
    ) -> None:
        """previous_state and current_state carry host status strings."""
        host_id = await _make_host(host_repo, "10.3.0.2")
        event = _host_unavailable_event()

        record = await event_repo.create(host_id=host_id, scan_id=None, event=event)
        record_id = record.id
        pg_session.expire_all()
        fetched = await event_repo.get_by_id(record_id)

        assert fetched is not None
        assert fetched.previous_state == "available"
        assert fetched.current_state == "unavailable"


# ---------------------------------------------------------------------------
# create — timestamp preservation
# ---------------------------------------------------------------------------


class TestTimestampPreservation:
    async def test_created_at_uses_event_timestamp(
        self,
        host_repo: HostRepository,
        event_repo: MonitoringEventRepository,
        pg_session: AsyncSession,
    ) -> None:
        """created_at must equal the domain event's timestamp, not datetime.now()."""
        host_id = await _make_host(host_repo, "10.4.0.1")
        custom_ts = datetime(2025, 6, 15, 10, 30, 0, tzinfo=UTC)
        event = _port_opened_event(80, timestamp=custom_ts)

        record = await event_repo.create(host_id=host_id, scan_id=None, event=event)
        record_id = record.id
        pg_session.expire_all()
        fetched = await event_repo.get_by_id(record_id)

        assert fetched is not None
        # Allow for timezone representation differences (aware vs UTC)
        ca = fetched.created_at
        fetched_utc = ca.replace(tzinfo=UTC) if ca.tzinfo is None else ca
        assert fetched_utc.year == 2025
        assert fetched_utc.month == 6
        assert fetched_utc.day == 15
        assert fetched_utc.hour == 10
        assert fetched_utc.minute == 30


# ---------------------------------------------------------------------------
# create_many
# ---------------------------------------------------------------------------


class TestCreateMany:
    async def test_create_many_persists_all_events(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        event_repo: MonitoringEventRepository,
        pg_session: AsyncSession,
    ) -> None:
        """create_many must persist exactly as many records as events provided."""
        host_id = await _make_host(host_repo, "10.5.0.1")
        scan_id = await _make_scan(scan_repo, host_id)

        events = [
            _port_closed_event(22),
            _port_opened_event(443),
            _host_available_event(),
        ]
        records = await event_repo.create_many(
            host_id=host_id, scan_id=scan_id, events=events
        )

        assert len(records) == 3
        types = [r.event_type for r in records]
        assert "port_closed" in types
        assert "port_opened" in types
        assert "host_became_available" in types

    async def test_create_many_empty_returns_empty_list(
        self,
        host_repo: HostRepository,
        event_repo: MonitoringEventRepository,
    ) -> None:
        """create_many with empty list must return [] without DB operations."""
        host_id = await _make_host(host_repo, "10.5.0.2")
        result = await event_repo.create_many(host_id=host_id, scan_id=None, events=[])
        assert result == []

    async def test_create_many_records_are_findable(
        self,
        host_repo: HostRepository,
        event_repo: MonitoringEventRepository,
        pg_session: AsyncSession,
    ) -> None:
        """Records created by create_many must be retrievable via list_by_host."""
        host_id = await _make_host(host_repo, "10.5.0.3")
        events = [_port_opened_event(80), _port_opened_event(443)]

        await event_repo.create_many(host_id=host_id, scan_id=None, events=events)
        pg_session.expire_all()

        all_records = await event_repo.list_by_host(host_id)
        assert len(all_records) == 2


# ---------------------------------------------------------------------------
# get_by_id
# ---------------------------------------------------------------------------


class TestGetById:
    async def test_returns_record_when_found(
        self,
        host_repo: HostRepository,
        event_repo: MonitoringEventRepository,
    ) -> None:
        host_id = await _make_host(host_repo, "10.6.0.1")
        record = await event_repo.create(
            host_id=host_id, scan_id=None, event=_port_opened_event(80)
        )
        fetched = await event_repo.get_by_id(record.id)
        assert fetched is not None
        assert fetched.id == record.id

    async def test_returns_none_when_not_found(
        self, event_repo: MonitoringEventRepository
    ) -> None:
        result = await event_repo.get_by_id(999_999_999)
        assert result is None

    async def test_does_not_raise_on_missing(
        self, event_repo: MonitoringEventRepository
    ) -> None:
        result = await event_repo.get_by_id(0)
        assert result is None


# ---------------------------------------------------------------------------
# list_by_host
# ---------------------------------------------------------------------------


class TestListByHost:
    async def test_returns_only_host_events(
        self,
        host_repo: HostRepository,
        event_repo: MonitoringEventRepository,
        pg_session: AsyncSession,
    ) -> None:
        """list_by_host must not return events from other hosts."""
        host_a = await _make_host(host_repo, "10.7.0.1")
        host_b = await _make_host(host_repo, "10.7.0.2")

        await event_repo.create(
            host_id=host_a, scan_id=None, event=_port_opened_event(80)
        )
        await event_repo.create(
            host_id=host_a, scan_id=None, event=_port_opened_event(443)
        )
        await event_repo.create(
            host_id=host_b, scan_id=None, event=_host_available_event()
        )
        pg_session.expire_all()

        records_a = await event_repo.list_by_host(host_a)
        assert len(records_a) == 2
        assert all(r.host_id == host_a for r in records_a)

        records_b = await event_repo.list_by_host(host_b)
        assert len(records_b) == 1

    async def test_returns_most_recent_first(
        self,
        host_repo: HostRepository,
        event_repo: MonitoringEventRepository,
        pg_session: AsyncSession,
    ) -> None:
        """list_by_host must return events in created_at DESC order."""
        host_id = await _make_host(host_repo, "10.7.0.3")

        t1 = _NOW
        t2 = _NOW + timedelta(minutes=5)
        t3 = _NOW + timedelta(minutes=10)

        await event_repo.create(
            host_id=host_id,
            scan_id=None,
            event=_port_opened_event(80, timestamp=t1),
        )
        await event_repo.create(
            host_id=host_id,
            scan_id=None,
            event=_port_opened_event(443, timestamp=t3),
        )
        await event_repo.create(
            host_id=host_id,
            scan_id=None,
            event=_port_opened_event(22, timestamp=t2),
        )
        pg_session.expire_all()

        records = await event_repo.list_by_host(host_id)
        timestamps = [r.created_at for r in records]
        for i in range(len(timestamps) - 1):
            assert timestamps[i] >= timestamps[i + 1], (
                f"Expected DESC order, got {timestamps}"
            )

    async def test_limit_restricts_results(
        self,
        host_repo: HostRepository,
        event_repo: MonitoringEventRepository,
        pg_session: AsyncSession,
    ) -> None:
        host_id = await _make_host(host_repo, "10.7.0.4")
        for i in range(5):
            await event_repo.create(
                host_id=host_id,
                scan_id=None,
                event=_port_opened_event(80 + i, timestamp=_NOW + timedelta(minutes=i)),
            )
        pg_session.expire_all()

        records = await event_repo.list_by_host(host_id, limit=3)
        assert len(records) == 3

    async def test_returns_empty_for_unknown_host(
        self, event_repo: MonitoringEventRepository
    ) -> None:
        records = await event_repo.list_by_host(999_999_999)
        assert records == []

    async def test_invalid_limit_raises(
        self, event_repo: MonitoringEventRepository
    ) -> None:
        with pytest.raises(ValueError):
            await event_repo.list_by_host(1, limit=0)


# ---------------------------------------------------------------------------
# list_by_scan
# ---------------------------------------------------------------------------


class TestListByScan:
    async def test_returns_only_scan_events(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        event_repo: MonitoringEventRepository,
        pg_session: AsyncSession,
    ) -> None:
        """list_by_scan must not return events from other scans."""
        host_id = await _make_host(host_repo, "10.8.0.1")
        scan_a = await _make_scan(scan_repo, host_id, started_at=_NOW)
        scan_b = await _make_scan(
            scan_repo, host_id, started_at=_NOW + timedelta(minutes=5)
        )

        await event_repo.create_many(
            host_id=host_id,
            scan_id=scan_a,
            events=[_port_opened_event(80), _host_available_event()],
        )
        await event_repo.create(
            host_id=host_id, scan_id=scan_b, event=_port_closed_event(22)
        )
        pg_session.expire_all()

        records_a = await event_repo.list_by_scan(scan_a)
        assert len(records_a) == 2
        assert all(r.scan_id == scan_a for r in records_a)

        records_b = await event_repo.list_by_scan(scan_b)
        assert len(records_b) == 1

    async def test_list_by_scan_ordered_by_id_asc(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        event_repo: MonitoringEventRepository,
        pg_session: AsyncSession,
    ) -> None:
        """list_by_scan must return events in id ASC order."""
        host_id = await _make_host(host_repo, "10.8.0.2")
        scan_id = await _make_scan(scan_repo, host_id)

        await event_repo.create_many(
            host_id=host_id,
            scan_id=scan_id,
            events=[
                _host_unavailable_event(),
                _port_closed_event(22),
                _port_closed_event(80),
            ],
        )
        pg_session.expire_all()

        records = await event_repo.list_by_scan(scan_id)
        ids = [r.id for r in records]
        assert ids == sorted(ids), f"Expected ASC id order, got {ids}"

    async def test_returns_empty_for_unknown_scan(
        self, event_repo: MonitoringEventRepository
    ) -> None:
        records = await event_repo.list_by_scan(999_999_999)
        assert records == []


# ---------------------------------------------------------------------------
# FK violation
# ---------------------------------------------------------------------------


class TestFKViolation:
    async def test_invalid_host_id_raises_integrity_error(
        self,
        event_repo: MonitoringEventRepository,
    ) -> None:
        """FK violation on host_id must raise IntegrityError."""
        with pytest.raises(IntegrityError):
            await event_repo.create(
                host_id=999_999_999,
                scan_id=None,
                event=_port_opened_event(80),
            )

    async def test_session_usable_after_rollback(
        self,
        host_repo: HostRepository,
        event_repo: MonitoringEventRepository,
        pg_session: AsyncSession,
    ) -> None:
        """After FK violation + rollback the session must be reusable."""
        try:
            await event_repo.create(
                host_id=999_999_999,
                scan_id=None,
                event=_port_opened_event(80),
            )
        except IntegrityError:
            await pg_session.rollback()

        # Session now clean; perform a valid operation
        host_id = await _make_host(host_repo, "10.9.0.1")
        record = await event_repo.create(
            host_id=host_id, scan_id=None, event=_host_available_event()
        )
        assert record.id is not None


# ---------------------------------------------------------------------------
# Atomicity: scan + port_results + events rolled back together
# ---------------------------------------------------------------------------


class TestAtomicity:
    async def test_rollback_undoes_scan_and_events(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        event_repo: MonitoringEventRepository,
        pg_session: AsyncSession,
    ) -> None:
        """Rolling back must discard the scan, port results, AND events."""
        from app.repositories.scan import PortResultInput

        host_id = await _make_host(host_repo, "10.10.0.1")
        scan_id = await _make_scan(scan_repo, host_id)

        await scan_repo.add_port_results(
            scan_id=scan_id,
            results=[PortResultInput(port=80, status="open", response_time_ms=1.0)],
        )
        await event_repo.create_many(
            host_id=host_id,
            scan_id=scan_id,
            events=[_host_available_event(), _port_opened_event(80)],
        )
        await pg_session.flush()

        # Rollback the entire transaction
        await pg_session.rollback()

        # After rollback nothing should exist
        scan_records = await event_repo.list_by_scan(scan_id)
        assert scan_records == [], (
            "Events must not persist after rollback — no hidden commit"
        )
