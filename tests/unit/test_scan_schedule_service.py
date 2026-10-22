"""Unit tests for ScanScheduleService validation (no database)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.scan_schedule import (
    MAX_SCHEDULE_PORTS,
    InvalidScheduleError,
    ScanScheduleService,
    ScheduleNotFoundError,
    normalize_schedule_ports,
)

_NOW = datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC)


def test_normalize_ports_sorts_and_deduplicates() -> None:
    assert normalize_schedule_ports([443, 22, 80, 22]) == [22, 80, 443]


@pytest.mark.parametrize("ports", [[], [0], [65536], [-1, 22]])
def test_normalize_ports_rejects_invalid(ports: list[int]) -> None:
    with pytest.raises(InvalidScheduleError):
        normalize_schedule_ports(ports)


def test_normalize_ports_caps_the_list() -> None:
    with pytest.raises(InvalidScheduleError, match="at most"):
        normalize_schedule_ports(list(range(1, MAX_SCHEDULE_PORTS + 2)))
    assert len(normalize_schedule_ports(list(range(1, MAX_SCHEDULE_PORTS + 1)))) == (
        MAX_SCHEDULE_PORTS
    )


async def test_create_rejects_invalid_target_before_touching_db() -> None:
    session = AsyncMock()
    service = ScanScheduleService(session, min_interval=60)
    with pytest.raises(InvalidScheduleError, match="Invalid target"):
        await service.create_schedule(
            target="not a host!", ports=[22], interval_seconds=300, now=_NOW
        )
    session.commit.assert_not_awaited()


async def test_create_rejects_interval_below_minimum() -> None:
    session = AsyncMock()
    service = ScanScheduleService(session, min_interval=60)
    with pytest.raises(InvalidScheduleError, match="at least 60"):
        await service.create_schedule(
            target="127.0.0.1", ports=[22], interval_seconds=59, now=_NOW
        )
    session.commit.assert_not_awaited()


async def test_update_unknown_schedule_raises_and_rolls_back() -> None:
    session = AsyncMock()
    service = ScanScheduleService(session, min_interval=60)
    with (
        patch.object(
            service._schedule_repo, "get_by_id", new=AsyncMock(return_value=None)
        ),
        pytest.raises(ScheduleNotFoundError),
    ):
        await service.update_schedule(99, enabled=False, now=_NOW)
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()


def _schedule(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": 1,
        "host_id": 7,
        "host": SimpleNamespace(address="127.0.0.1", name=None),
        "ports": [22],
        "interval_seconds": 3600,
        "enabled": True,
        "next_run_at": _NOW + timedelta(hours=1),
        "last_run_at": None,
        "last_scan_id": None,
        "last_error": None,
        "created_at": _NOW,
        "updated_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


async def _update(schedule: SimpleNamespace, **kwargs: object) -> dict[str, object]:
    """Run update_schedule and return the kwargs passed to the repository."""
    session = AsyncMock()
    service = ScanScheduleService(session, min_interval=60)
    update = AsyncMock(return_value=schedule)
    with (
        patch.object(
            service._schedule_repo, "get_by_id", new=AsyncMock(return_value=schedule)
        ),
        patch.object(service._schedule_repo, "update", new=update),
    ):
        await service.update_schedule(1, now=_NOW, **kwargs)  # type: ignore[arg-type]
    session.commit.assert_awaited_once()
    return dict(update.await_args.kwargs)  # type: ignore[union-attr]


async def test_reenabling_makes_schedule_due_now() -> None:
    kwargs = await _update(_schedule(enabled=False), enabled=True)
    assert kwargs["enabled"] is True
    assert kwargs["next_run_at"] == _NOW


async def test_shorter_interval_brings_next_run_forward() -> None:
    kwargs = await _update(_schedule(), interval_seconds=60)
    assert kwargs["interval_seconds"] == 60
    assert kwargs["next_run_at"] == _NOW + timedelta(seconds=60)


async def test_longer_interval_keeps_next_run() -> None:
    kwargs = await _update(_schedule(), interval_seconds=7200)
    assert kwargs["next_run_at"] == _NOW + timedelta(hours=1)


async def test_update_normalizes_ports() -> None:
    kwargs = await _update(_schedule(), ports=[443, 22, 443])
    assert kwargs["ports"] == [22, 443]
