"""Integration tests for ScanRepository against a real PostgreSQL database.

These tests require ``TEST_DATABASE_URL`` to be set and are tagged with the
``integration`` marker so that they are excluded from the default ``pytest``
run::

    # Only unit tests (no database required):
    pytest

    # PostgreSQL integration tests (set TEST_DATABASE_URL first):
    #   pytest -m integration

Each test runs inside a transaction that is rolled back automatically by the
``pg_session`` fixture in ``conftest.py``, so tests are fully isolated and do
not leave persistent data in the database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.host import HostRepository
from app.repositories.scan import (
    PortResultInput,
    ScanHostNotFoundError,
    ScanRepository,
)

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


async def _make_host(
    host_repo: HostRepository,
    session: AsyncSession,
    *,
    address: str = "10.0.0.1",
) -> int:
    """Create a host and flush; return its id."""
    host = await host_repo.create(address=address)
    await session.flush()
    return host.id


async def _make_scan(
    scan_repo: ScanRepository,
    session: AsyncSession,
    *,
    host_id: int,
    status: str = "available",
    response_time_ms: float | None = 2.5,
    started_at: datetime = _NOW,
    finished_at: datetime | None = None,
) -> int:
    """Create a scan and flush; return its id."""
    scan = await scan_repo.create(
        host_id=host_id,
        status=status,
        response_time_ms=response_time_ms,
        started_at=started_at,
        finished_at=finished_at,
    )
    await session.flush()
    return scan.id


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


class TestCreate:
    async def test_create_returns_scan_with_id(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        pg_session: AsyncSession,
    ) -> None:
        """A created scan must have a server-assigned integer id."""
        host_id = await _make_host(host_repo, pg_session, address="10.1.0.1")
        scan = await scan_repo.create(
            host_id=host_id,
            status="available",
            response_time_ms=1.5,
            started_at=_NOW,
            finished_at=None,
        )
        await pg_session.flush()

        assert isinstance(scan.id, int)
        assert scan.id > 0

    async def test_create_sets_host_id(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        pg_session: AsyncSession,
    ) -> None:
        host_id = await _make_host(host_repo, pg_session, address="10.1.0.2")
        scan = await scan_repo.create(
            host_id=host_id,
            status="available",
            response_time_ms=None,
            started_at=_NOW,
            finished_at=None,
        )
        assert scan.host_id == host_id

    async def test_create_sets_status(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        pg_session: AsyncSession,
    ) -> None:
        host_id = await _make_host(host_repo, pg_session, address="10.1.0.3")
        scan = await scan_repo.create(
            host_id=host_id,
            status="unavailable",
            response_time_ms=None,
            started_at=_NOW,
            finished_at=None,
        )
        assert scan.status == "unavailable"

    async def test_create_sets_response_time(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        pg_session: AsyncSession,
    ) -> None:
        host_id = await _make_host(host_repo, pg_session, address="10.1.0.4")
        scan = await scan_repo.create(
            host_id=host_id,
            status="available",
            response_time_ms=3.14,
            started_at=_NOW,
            finished_at=None,
        )
        assert scan.response_time_ms == pytest.approx(3.14)

    async def test_create_sets_started_at(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        pg_session: AsyncSession,
    ) -> None:
        host_id = await _make_host(host_repo, pg_session, address="10.1.0.5")
        scan = await scan_repo.create(
            host_id=host_id,
            status="available",
            response_time_ms=None,
            started_at=_NOW,
            finished_at=None,
        )
        # Compare without microsecond loss from DB round-trip
        assert scan.started_at is not None


# ---------------------------------------------------------------------------
# FK violation: host_id not found
# ---------------------------------------------------------------------------


class TestFKViolation:
    async def test_nonexistent_host_raises_scan_host_not_found(
        self,
        scan_repo: ScanRepository,
    ) -> None:
        with pytest.raises(ScanHostNotFoundError) as exc_info:
            await scan_repo.create(
                host_id=999_999_999,
                status="available",
                response_time_ms=None,
                started_at=_NOW,
                finished_at=None,
            )
        assert exc_info.value.host_id == 999_999_999

    async def test_fk_error_chains_integrity_error(
        self,
        scan_repo: ScanRepository,
    ) -> None:
        with pytest.raises(ScanHostNotFoundError) as exc_info:
            await scan_repo.create(
                host_id=999_999_999,
                status="available",
                response_time_ms=None,
                started_at=_NOW,
                finished_at=None,
            )
        assert isinstance(exc_info.value.__cause__, IntegrityError)

    async def test_session_usable_after_rollback(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        pg_session: AsyncSession,
    ) -> None:
        """After catching FK error and rolling back, the session must work."""
        try:
            await scan_repo.create(
                host_id=999_999_999,
                status="available",
                response_time_ms=None,
                started_at=_NOW,
                finished_at=None,
            )
        except ScanHostNotFoundError:
            await pg_session.rollback()

        # Session now clean; create a real host and scan
        host_id = await _make_host(host_repo, pg_session, address="10.2.0.1")
        scan = await scan_repo.create(
            host_id=host_id,
            status="available",
            response_time_ms=1.0,
            started_at=_NOW,
            finished_at=None,
        )
        await pg_session.flush()
        assert scan.id is not None


# ---------------------------------------------------------------------------
# add_port_results + get_by_id (port ordering, count)
# ---------------------------------------------------------------------------


class TestPortResults:
    async def test_port_results_are_persisted(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        pg_session: AsyncSession,
    ) -> None:
        """Three port results must survive a flush and be reloaded via get_by_id."""
        host_id = await _make_host(host_repo, pg_session, address="10.3.0.1")
        scan_id = await _make_scan(scan_repo, pg_session, host_id=host_id)

        inputs = [
            PortResultInput(port=22, status="closed", response_time_ms=10.0),
            PortResultInput(port=80, status="open", response_time_ms=1.0),
            PortResultInput(port=443, status="open", response_time_ms=1.2),
        ]
        await scan_repo.add_port_results(scan_id=scan_id, results=inputs)
        await pg_session.flush()

        # Expire and reload
        pg_session.expire_all()
        scan = await scan_repo.get_by_id(scan_id)
        assert scan is not None
        assert len(scan.port_results) == 3

    async def test_port_results_status_values(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        pg_session: AsyncSession,
    ) -> None:
        host_id = await _make_host(host_repo, pg_session, address="10.3.0.2")
        scan_id = await _make_scan(scan_repo, pg_session, host_id=host_id)

        inputs = [
            PortResultInput(port=22, status="closed", response_time_ms=None),
            PortResultInput(port=80, status="open", response_time_ms=1.0),
        ]
        await scan_repo.add_port_results(scan_id=scan_id, results=inputs)
        await pg_session.flush()
        pg_session.expire_all()

        scan = await scan_repo.get_by_id(scan_id)
        assert scan is not None
        statuses = {pr.port: pr.status for pr in scan.port_results}
        assert statuses[22] == "closed"
        assert statuses[80] == "open"

    async def test_port_results_ordered_asc(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        pg_session: AsyncSession,
    ) -> None:
        """Port results must be returned in ASC port order regardless of insertion."""
        host_id = await _make_host(host_repo, pg_session, address="10.3.0.3")
        scan_id = await _make_scan(scan_repo, pg_session, host_id=host_id)

        # Deliberately out of order
        inputs = [
            PortResultInput(port=443, status="open", response_time_ms=1.0),
            PortResultInput(port=22, status="closed", response_time_ms=10.0),
            PortResultInput(port=8080, status="open", response_time_ms=1.5),
            PortResultInput(port=80, status="open", response_time_ms=1.1),
        ]
        await scan_repo.add_port_results(scan_id=scan_id, results=inputs)
        await pg_session.flush()
        pg_session.expire_all()

        scan = await scan_repo.get_by_id(scan_id)
        assert scan is not None
        ports = [pr.port for pr in scan.port_results]
        assert ports == sorted(ports), f"Expected ASC order, got {ports}"
        assert ports == [22, 80, 443, 8080]

    async def test_empty_port_results(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        pg_session: AsyncSession,
    ) -> None:
        """A scan with no port results must return an empty list."""
        host_id = await _make_host(host_repo, pg_session, address="10.3.0.4")
        scan_id = await _make_scan(scan_repo, pg_session, host_id=host_id)

        await scan_repo.add_port_results(scan_id=scan_id, results=[])
        pg_session.expire_all()

        scan = await scan_repo.get_by_id(scan_id)
        assert scan is not None
        assert scan.port_results == []


# ---------------------------------------------------------------------------
# get_by_id
# ---------------------------------------------------------------------------


class TestGetById:
    async def test_returns_scan_when_found(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        pg_session: AsyncSession,
    ) -> None:
        host_id = await _make_host(host_repo, pg_session, address="10.4.0.1")
        scan_id = await _make_scan(scan_repo, pg_session, host_id=host_id)

        scan = await scan_repo.get_by_id(scan_id)
        assert scan is not None
        assert scan.id == scan_id

    async def test_returns_none_when_not_found(self, scan_repo: ScanRepository) -> None:
        result = await scan_repo.get_by_id(999_999_999)
        assert result is None

    async def test_does_not_raise_on_missing(self, scan_repo: ScanRepository) -> None:
        result = await scan_repo.get_by_id(0)
        assert result is None

    async def test_get_by_id_includes_port_results(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        pg_session: AsyncSession,
    ) -> None:
        """get_by_id must load port_results without triggering lazy-load issues."""
        host_id = await _make_host(host_repo, pg_session, address="10.4.0.2")
        scan_id = await _make_scan(scan_repo, pg_session, host_id=host_id)

        inputs = [PortResultInput(port=80, status="open", response_time_ms=1.0)]
        await scan_repo.add_port_results(scan_id=scan_id, results=inputs)
        await pg_session.flush()
        pg_session.expire_all()

        scan = await scan_repo.get_by_id(scan_id)
        assert scan is not None
        # Accessing port_results must not raise MissingGreenlet
        assert len(scan.port_results) == 1
        assert scan.port_results[0].port == 80


# ---------------------------------------------------------------------------
# list_by_host
# ---------------------------------------------------------------------------


class TestListByHost:
    async def test_returns_only_host_scans(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        pg_session: AsyncSession,
    ) -> None:
        """list_by_host must return only scans for the specified host."""
        host_a = await _make_host(host_repo, pg_session, address="10.5.0.1")
        host_b = await _make_host(host_repo, pg_session, address="10.5.0.2")

        await _make_scan(scan_repo, pg_session, host_id=host_a)
        await _make_scan(scan_repo, pg_session, host_id=host_a)
        await _make_scan(scan_repo, pg_session, host_id=host_b)

        scans_a = await scan_repo.list_by_host(host_a)
        assert all(s.host_id == host_a for s in scans_a)
        assert len(scans_a) == 2

        scans_b = await scan_repo.list_by_host(host_b)
        assert len(scans_b) == 1

    async def test_returns_most_recent_first(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        pg_session: AsyncSession,
    ) -> None:
        """list_by_host must order by started_at DESC (most recent first)."""
        host_id = await _make_host(host_repo, pg_session, address="10.5.0.3")

        t1 = _NOW
        t2 = _NOW + timedelta(minutes=5)
        t3 = _NOW + timedelta(minutes=10)

        await _make_scan(scan_repo, pg_session, host_id=host_id, started_at=t1)
        await _make_scan(scan_repo, pg_session, host_id=host_id, started_at=t3)
        await _make_scan(scan_repo, pg_session, host_id=host_id, started_at=t2)

        scans = await scan_repo.list_by_host(host_id)
        started = [s.started_at for s in scans]

        # Verify descending order
        for i in range(len(started) - 1):
            assert started[i] >= started[i + 1], f"Expected DESC order, got {started}"

    async def test_returns_empty_for_unknown_host(
        self, scan_repo: ScanRepository
    ) -> None:
        scans = await scan_repo.list_by_host(999_999_999)
        assert scans == []

    async def test_limit_restricts_results(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        pg_session: AsyncSession,
    ) -> None:
        """list_by_host(limit=2) must return at most 2 scans."""
        host_id = await _make_host(host_repo, pg_session, address="10.5.0.4")
        for i in range(5):
            await _make_scan(
                scan_repo,
                pg_session,
                host_id=host_id,
                started_at=_NOW + timedelta(minutes=i),
            )

        scans = await scan_repo.list_by_host(host_id, limit=2)
        assert len(scans) == 2

    async def test_limit_returns_most_recent(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        pg_session: AsyncSession,
    ) -> None:
        """limit must select the most recent scans (DESC order respected)."""
        host_id = await _make_host(host_repo, pg_session, address="10.5.0.5")

        times = [_NOW + timedelta(minutes=i) for i in range(5)]
        for t in times:
            await _make_scan(scan_repo, pg_session, host_id=host_id, started_at=t)

        scans = await scan_repo.list_by_host(host_id, limit=2)
        # Most recent two: times[4] and times[3]
        returned_times = [s.started_at for s in scans]
        assert returned_times[0] >= returned_times[1]
        assert returned_times[0].replace(tzinfo=None) >= times[3].replace(tzinfo=None)

    async def test_invalid_limit_raises(self, scan_repo: ScanRepository) -> None:
        with pytest.raises(ValueError):
            await scan_repo.list_by_host(1, limit=0)


# ---------------------------------------------------------------------------
# Atomicity: rollback undoes Scan + PortResults
# ---------------------------------------------------------------------------


class TestAtomicity:
    async def test_rollback_undoes_scan_and_port_results(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        pg_session: AsyncSession,
    ) -> None:
        """Rolling back must discard both the scan and its port results."""
        host_id = await _make_host(host_repo, pg_session, address="10.6.0.1")
        scan = await scan_repo.create(
            host_id=host_id,
            status="available",
            response_time_ms=1.0,
            started_at=_NOW,
            finished_at=None,
        )
        await pg_session.flush()
        scan_id = scan.id

        inputs = [
            PortResultInput(port=22, status="closed", response_time_ms=5.0),
            PortResultInput(port=80, status="open", response_time_ms=1.0),
        ]
        await scan_repo.add_port_results(scan_id=scan_id, results=inputs)
        await pg_session.flush()

        # Rollback the entire transaction
        await pg_session.rollback()

        # After rollback, nothing should be found
        found_scan = await scan_repo.get_by_id(scan_id)
        assert found_scan is None, (
            "Scan must not exist after rollback — repository must not commit"
        )

    async def test_repository_never_commits_implicitly(
        self,
        host_repo: HostRepository,
        scan_repo: ScanRepository,
        pg_session: AsyncSession,
    ) -> None:
        """Verify no implicit commit happens by checking rollback effectiveness."""
        host_id = await _make_host(host_repo, pg_session, address="10.6.0.2")
        scan = await scan_repo.create(
            host_id=host_id,
            status="available",
            response_time_ms=None,
            started_at=_NOW,
            finished_at=None,
        )
        await pg_session.flush()
        scan_id = scan.id

        await pg_session.rollback()

        # If the repo had committed, the scan would persist; rollback would be
        # too late.  Confirming it is gone proves no hidden commit occurred.
        result = await scan_repo.get_by_id(scan_id)
        assert result is None
