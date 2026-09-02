"""Unit tests for ScanRepository.

These tests use ``AsyncMock`` / ``MagicMock`` to simulate the SQLAlchemy
``AsyncSession``.  No live database is required.

The goal is to verify that the repository issues the correct session calls
and raises the correct exceptions.  Real SQL behaviour (FK constraints,
ordering, selectinload) is validated in the integration tests.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.port_result import PortResult
from app.models.scan import Scan
from app.repositories.scan import (
    PortResultInput,
    ScanHostNotFoundError,
    ScanRepository,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _make_session() -> MagicMock:
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.get = AsyncMock()
    session.scalar = AsyncMock()
    session.execute = AsyncMock()
    return session


def _make_scan(
    *,
    scan_id: int = 1,
    host_id: int = 10,
    status: str = "available",
) -> Scan:
    scan = Scan(
        host_id=host_id,
        status=status,
        response_time_ms=1.5,
        started_at=_NOW,
        finished_at=None,
    )
    scan.id = scan_id  # type: ignore[assignment]
    return scan


# ---------------------------------------------------------------------------
# create — happy path
# ---------------------------------------------------------------------------


class TestCreate:
    @pytest.mark.asyncio
    async def test_create_adds_flushes_refreshes(self) -> None:
        """create() must call add → flush → refresh in order."""
        session = _make_session()
        scan = _make_scan()

        with patch("app.repositories.scan.Scan", return_value=scan):
            repo = ScanRepository(session)
            result = await repo.create(
                host_id=10,
                status="available",
                response_time_ms=1.5,
                started_at=_NOW,
                finished_at=None,
            )

        session.add.assert_called_once_with(scan)
        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once_with(scan)
        assert result is scan

    @pytest.mark.asyncio
    async def test_create_does_not_commit(self) -> None:
        session = _make_session()
        session.commit = AsyncMock()

        with patch("app.repositories.scan.Scan", return_value=_make_scan()):
            repo = ScanRepository(session)
            await repo.create(
                host_id=10,
                status="available",
                response_time_ms=None,
                started_at=_NOW,
                finished_at=None,
            )

        session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_passes_all_fields(self) -> None:
        """create() must forward all arguments to the Scan constructor."""
        session = _make_session()

        with patch("app.repositories.scan.Scan") as MockScan:
            instance = _make_scan()
            MockScan.return_value = instance
            repo = ScanRepository(session)
            await repo.create(
                host_id=7,
                status="unavailable",
                response_time_ms=42.5,
                started_at=_NOW,
                finished_at=_NOW,
            )
            MockScan.assert_called_once_with(
                host_id=7,
                status="unavailable",
                response_time_ms=42.5,
                started_at=_NOW,
                finished_at=_NOW,
            )


# ---------------------------------------------------------------------------
# create — FK violation → ScanHostNotFoundError
# ---------------------------------------------------------------------------


class TestCreateFKViolation:
    @pytest.mark.asyncio
    async def test_fk_raises_scan_host_not_found(self) -> None:
        session = _make_session()
        session.flush = AsyncMock(
            side_effect=IntegrityError(
                "FK", params={}, orig=Exception("fk_scans_host_id")
            )
        )

        with patch("app.repositories.scan.Scan", return_value=_make_scan()):
            repo = ScanRepository(session)
            with pytest.raises(ScanHostNotFoundError) as exc_info:
                await repo.create(
                    host_id=999,
                    status="available",
                    response_time_ms=None,
                    started_at=_NOW,
                    finished_at=None,
                )

        assert exc_info.value.host_id == 999

    @pytest.mark.asyncio
    async def test_fk_chains_original_error(self) -> None:
        session = _make_session()
        original = IntegrityError("FK", params={}, orig=Exception("fk"))
        session.flush = AsyncMock(side_effect=original)

        with patch("app.repositories.scan.Scan", return_value=_make_scan()):
            repo = ScanRepository(session)
            with pytest.raises(ScanHostNotFoundError) as exc_info:
                await repo.create(
                    host_id=999,
                    status="available",
                    response_time_ms=None,
                    started_at=_NOW,
                    finished_at=None,
                )

        assert exc_info.value.__cause__ is original

    @pytest.mark.asyncio
    async def test_fk_does_not_rollback(self) -> None:
        """Repository must NOT rollback — that is the caller's responsibility."""
        session = _make_session()
        session.rollback = AsyncMock()
        session.flush = AsyncMock(
            side_effect=IntegrityError("FK", params={}, orig=Exception("fk"))
        )

        with patch("app.repositories.scan.Scan", return_value=_make_scan()):
            repo = ScanRepository(session)
            with pytest.raises(ScanHostNotFoundError):
                await repo.create(
                    host_id=999,
                    status="available",
                    response_time_ms=None,
                    started_at=_NOW,
                    finished_at=None,
                )

        session.rollback.assert_not_called()


# ---------------------------------------------------------------------------
# add_port_results
# ---------------------------------------------------------------------------


class TestAddPortResults:
    @pytest.mark.asyncio
    async def test_adds_all_rows_then_one_flush(self) -> None:
        """All PortResult rows must be add()ed before a single flush()."""
        session = _make_session()
        repo = ScanRepository(session)

        inputs = [
            PortResultInput(port=22, status="closed", response_time_ms=10.0),
            PortResultInput(port=80, status="open", response_time_ms=1.0),
            PortResultInput(port=443, status="open", response_time_ms=1.2),
        ]

        with patch("app.repositories.scan.PortResult") as MockPR:
            instances = [MagicMock(spec=PortResult) for _ in inputs]
            MockPR.side_effect = instances
            results = await repo.add_port_results(scan_id=1, results=inputs)

        # Three add() calls, one flush
        assert session.add.call_count == 3
        session.flush.assert_awaited_once()
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_empty_results_no_flush(self) -> None:
        """An empty results list must not trigger any session operations."""
        session = _make_session()
        repo = ScanRepository(session)

        output = await repo.add_port_results(scan_id=1, results=[])

        session.add.assert_not_called()
        session.flush.assert_not_awaited()
        assert output == []

    @pytest.mark.asyncio
    async def test_port_result_constructed_correctly(self) -> None:
        """PortResult must be constructed with correct scan_id and input fields."""
        session = _make_session()
        repo = ScanRepository(session)

        inputs = [PortResultInput(port=443, status="open", response_time_ms=1.5)]

        with patch("app.repositories.scan.PortResult") as MockPR:
            instance = MagicMock(spec=PortResult)
            MockPR.return_value = instance
            await repo.add_port_results(scan_id=7, results=inputs)

        MockPR.assert_called_once_with(
            scan_id=7,
            port=443,
            status="open",
            response_time_ms=1.5,
        )

    @pytest.mark.asyncio
    async def test_does_not_commit(self) -> None:
        session = _make_session()
        session.commit = AsyncMock()
        repo = ScanRepository(session)

        inputs = [PortResultInput(port=80, status="open", response_time_ms=1.0)]
        with patch("app.repositories.scan.PortResult", return_value=MagicMock()):
            await repo.add_port_results(scan_id=1, results=inputs)

        session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# get_by_id
# ---------------------------------------------------------------------------


class TestGetById:
    @pytest.mark.asyncio
    async def test_returns_scan_when_found(self) -> None:
        scan = _make_scan()
        session = _make_session()
        session.scalar = AsyncMock(return_value=scan)

        repo = ScanRepository(session)
        result = await repo.get_by_id(1)

        session.scalar.assert_awaited_once()
        assert result is scan

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self) -> None:
        session = _make_session()
        session.scalar = AsyncMock(return_value=None)

        repo = ScanRepository(session)
        result = await repo.get_by_id(999_999)

        assert result is None

    @pytest.mark.asyncio
    async def test_does_not_raise_on_missing(self) -> None:
        session = _make_session()
        session.scalar = AsyncMock(return_value=None)
        repo = ScanRepository(session)
        result = await repo.get_by_id(0)
        assert result is None


# ---------------------------------------------------------------------------
# list_by_host
# ---------------------------------------------------------------------------


class TestListByHost:
    @pytest.mark.asyncio
    async def test_returns_list(self) -> None:
        scans = [_make_scan(scan_id=1), _make_scan(scan_id=2)]
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = scans
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock

        session = _make_session()
        session.execute = AsyncMock(return_value=execute_result)

        repo = ScanRepository(session)
        result = await repo.list_by_host(host_id=10)

        session.execute.assert_awaited_once()
        assert result == scans

    @pytest.mark.asyncio
    async def test_returns_list_type(self) -> None:
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock

        session = _make_session()
        session.execute = AsyncMock(return_value=execute_result)

        repo = ScanRepository(session)
        result = await repo.list_by_host(host_id=10)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_invalid_limit_raises_value_error(self) -> None:
        session = _make_session()
        repo = ScanRepository(session)

        with pytest.raises(ValueError):
            await repo.list_by_host(host_id=1, limit=0)

    @pytest.mark.asyncio
    async def test_negative_limit_raises_value_error(self) -> None:
        session = _make_session()
        repo = ScanRepository(session)

        with pytest.raises(ValueError):
            await repo.list_by_host(host_id=1, limit=-5)


# ---------------------------------------------------------------------------
# ScanHostNotFoundError — public surface
# ---------------------------------------------------------------------------


class TestScanHostNotFoundError:
    def test_str_contains_host_id(self) -> None:
        err = ScanHostNotFoundError(42)
        assert "42" in str(err)

    def test_host_id_attribute(self) -> None:
        err = ScanHostNotFoundError(42)
        assert err.host_id == 42

    def test_is_exception(self) -> None:
        assert issubclass(ScanHostNotFoundError, Exception)


# ---------------------------------------------------------------------------
# PortResultInput — public surface
# ---------------------------------------------------------------------------


class TestPortResultInput:
    def test_is_frozen(self) -> None:
        """PortResultInput must be immutable."""
        pri = PortResultInput(port=80, status="open", response_time_ms=1.0)
        with pytest.raises((AttributeError, TypeError)):
            pri.port = 443  # type: ignore[misc]

    def test_fields(self) -> None:
        pri = PortResultInput(port=443, status="closed", response_time_ms=None)
        assert pri.port == 443
        assert pri.status == "closed"
        assert pri.response_time_ms is None
