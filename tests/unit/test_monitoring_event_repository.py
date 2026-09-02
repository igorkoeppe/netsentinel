"""Unit tests for MonitoringEventRepository.

Uses ``AsyncMock`` / ``MagicMock`` to simulate the SQLAlchemy ``AsyncSession``.
No live database is required.

The goal is to verify that the repository issues the correct session calls
and handles edge cases correctly.  Real SQL behaviour (FK constraints,
ordering, timestamp fidelity) is validated in the integration tests.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.detection.engine import MonitoringEvent, MonitoringEventType
from app.models.monitoring_event import MonitoringEventRecord
from app.monitoring.target import NetworkTarget
from app.repositories.monitoring_event import MonitoringEventRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_TARGET = NetworkTarget.parse("192.168.0.1")


def _make_session() -> MagicMock:
    session = MagicMock()
    session.add = MagicMock()
    session.add_all = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.get = AsyncMock()
    session.execute = AsyncMock()
    return session


def _make_event(
    event_type: MonitoringEventType = MonitoringEventType.HOST_BECAME_AVAILABLE,
    *,
    port: int | None = None,
    previous_state: str | None = None,
    current_state: str | None = None,
    timestamp: datetime = _NOW,
) -> MonitoringEvent:
    return MonitoringEvent(
        event_type=event_type,
        target=_TARGET,
        timestamp=timestamp,
        port=port,
        previous_state=previous_state,
        current_state=current_state,
    )


def _make_record(record_id: int = 1) -> MonitoringEventRecord:
    r = MonitoringEventRecord(
        host_id=1,
        scan_id=None,
        event_type="host_became_available",
        port=None,
        previous_state=None,
        current_state=None,
        created_at=_NOW,
    )
    r.id = record_id  # type: ignore[assignment]
    return r


# ---------------------------------------------------------------------------
# create — happy path
# ---------------------------------------------------------------------------


class TestCreate:
    @pytest.mark.asyncio
    async def test_create_adds_flushes_refreshes(self) -> None:
        """create() must call add → flush → refresh in order."""
        session = _make_session()
        record = _make_record()

        with patch(
            "app.repositories.monitoring_event.MonitoringEventRecord",
            return_value=record,
        ):
            repo = MonitoringEventRepository(session)
            result = await repo.create(
                host_id=1,
                scan_id=None,
                event=_make_event(),
            )

        session.add.assert_called_once_with(record)
        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once_with(record)
        assert result is record

    @pytest.mark.asyncio
    async def test_create_does_not_commit(self) -> None:
        session = _make_session()
        session.commit = AsyncMock()

        with patch(
            "app.repositories.monitoring_event.MonitoringEventRecord",
            return_value=_make_record(),
        ):
            repo = MonitoringEventRepository(session)
            await repo.create(host_id=1, scan_id=None, event=_make_event())

        session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_maps_event_fields(self) -> None:
        """create() must pass all mapped fields to MonitoringEventRecord."""
        session = _make_session()
        event = _make_event(
            MonitoringEventType.PORT_OPENED,
            port=443,
            previous_state="closed",
            current_state="open",
            timestamp=_NOW,
        )

        with patch(
            "app.repositories.monitoring_event.MonitoringEventRecord"
        ) as MockRecord:
            MockRecord.return_value = _make_record()
            repo = MonitoringEventRepository(session)
            await repo.create(host_id=5, scan_id=10, event=event)

        MockRecord.assert_called_once_with(
            host_id=5,
            scan_id=10,
            event_type="port_opened",
            port=443,
            previous_state="closed",
            current_state="open",
            created_at=_NOW,
        )

    @pytest.mark.asyncio
    async def test_create_host_event_null_port(self) -> None:
        """Host-level events must have port=None passed to the record."""
        session = _make_session()
        event = _make_event(
            MonitoringEventType.HOST_BECAME_UNAVAILABLE,
            port=None,
        )

        with patch(
            "app.repositories.monitoring_event.MonitoringEventRecord"
        ) as MockRecord:
            MockRecord.return_value = _make_record()
            repo = MonitoringEventRepository(session)
            await repo.create(host_id=1, scan_id=None, event=event)

        _, kwargs = MockRecord.call_args
        assert kwargs["port"] is None


# ---------------------------------------------------------------------------
# create_many
# ---------------------------------------------------------------------------


class TestCreateMany:
    @pytest.mark.asyncio
    async def test_create_many_uses_add_all_and_single_flush(self) -> None:
        """create_many must use add_all + one flush, not N individual adds."""
        session = _make_session()
        events = [
            _make_event(MonitoringEventType.PORT_CLOSED, port=22),
            _make_event(MonitoringEventType.PORT_OPENED, port=443),
            _make_event(MonitoringEventType.HOST_BECAME_AVAILABLE),
        ]

        repo = MonitoringEventRepository(session)
        results = await repo.create_many(host_id=1, scan_id=2, events=events)

        session.add_all.assert_called_once()
        session.flush.assert_awaited_once()
        # Individual add() must NOT be called
        session.add.assert_not_called()
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_create_many_empty_is_noop(self) -> None:
        """create_many with empty list must not touch the session."""
        session = _make_session()
        repo = MonitoringEventRepository(session)

        result = await repo.create_many(host_id=1, scan_id=None, events=[])

        session.add_all.assert_not_called()
        session.add.assert_not_called()
        session.flush.assert_not_awaited()
        assert result == []

    @pytest.mark.asyncio
    async def test_create_many_does_not_commit(self) -> None:
        session = _make_session()
        session.commit = AsyncMock()
        repo = MonitoringEventRepository(session)

        await repo.create_many(
            host_id=1,
            scan_id=None,
            events=[_make_event()],
        )

        session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_many_preserves_order(self) -> None:
        """create_many must pass records in the same order as events."""
        session = _make_session()
        events = [
            _make_event(MonitoringEventType.PORT_CLOSED, port=22),
            _make_event(MonitoringEventType.HOST_BECAME_UNAVAILABLE),
        ]
        repo = MonitoringEventRepository(session)
        results = await repo.create_many(host_id=1, scan_id=None, events=events)

        assert len(results) == 2
        assert results[0].event_type == "port_closed"
        assert results[1].event_type == "host_became_unavailable"


# ---------------------------------------------------------------------------
# get_by_id
# ---------------------------------------------------------------------------


class TestGetById:
    @pytest.mark.asyncio
    async def test_returns_record_when_found(self) -> None:
        record = _make_record()
        session = _make_session()
        session.get = AsyncMock(return_value=record)

        repo = MonitoringEventRepository(session)
        result = await repo.get_by_id(1)

        session.get.assert_awaited_once_with(MonitoringEventRecord, 1)
        assert result is record

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self) -> None:
        session = _make_session()
        session.get = AsyncMock(return_value=None)

        repo = MonitoringEventRepository(session)
        result = await repo.get_by_id(999_999)

        assert result is None

    @pytest.mark.asyncio
    async def test_does_not_raise_on_missing(self) -> None:
        session = _make_session()
        session.get = AsyncMock(return_value=None)
        repo = MonitoringEventRepository(session)
        result = await repo.get_by_id(0)
        assert result is None


# ---------------------------------------------------------------------------
# list_by_host
# ---------------------------------------------------------------------------


class TestListByHost:
    @pytest.mark.asyncio
    async def test_returns_list(self) -> None:
        records = [_make_record(1), _make_record(2)]
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = records
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock

        session = _make_session()
        session.execute = AsyncMock(return_value=execute_result)

        repo = MonitoringEventRepository(session)
        result = await repo.list_by_host(host_id=1)

        session.execute.assert_awaited_once()
        assert result == records

    @pytest.mark.asyncio
    async def test_returns_list_type(self) -> None:
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock

        session = _make_session()
        session.execute = AsyncMock(return_value=execute_result)

        repo = MonitoringEventRepository(session)
        result = await repo.list_by_host(host_id=1)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_invalid_limit_raises_value_error(self) -> None:
        session = _make_session()
        repo = MonitoringEventRepository(session)
        with pytest.raises(ValueError):
            await repo.list_by_host(host_id=1, limit=0)

    @pytest.mark.asyncio
    async def test_negative_limit_raises_value_error(self) -> None:
        session = _make_session()
        repo = MonitoringEventRepository(session)
        with pytest.raises(ValueError):
            await repo.list_by_host(host_id=1, limit=-1)


# ---------------------------------------------------------------------------
# list_by_scan
# ---------------------------------------------------------------------------


class TestListByScan:
    @pytest.mark.asyncio
    async def test_returns_list(self) -> None:
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [_make_record(1)]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock

        session = _make_session()
        session.execute = AsyncMock(return_value=execute_result)

        repo = MonitoringEventRepository(session)
        result = await repo.list_by_scan(scan_id=1)

        session.execute.assert_awaited_once()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_no_results(self) -> None:
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock

        session = _make_session()
        session.execute = AsyncMock(return_value=execute_result)

        repo = MonitoringEventRepository(session)
        result = await repo.list_by_scan(scan_id=999)
        assert result == []
