"""Unit tests for the in-process asyncio scheduler."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.monitoring.scheduler import Scheduler

_NOW = datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC)


def test_rejects_non_positive_poll_interval() -> None:
    async def tick(_now: datetime) -> None:
        return None

    with pytest.raises(ValueError):
        Scheduler(tick, poll_interval=0)


async def test_run_once_passes_clock_time_to_tick() -> None:
    seen: list[datetime] = []

    async def tick(now: datetime) -> None:
        seen.append(now)

    await Scheduler(tick, poll_interval=1, clock=lambda: _NOW).run_once()
    assert seen == [_NOW]


async def test_run_once_logs_and_swallows_tick_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def tick(_now: datetime) -> None:
        raise RuntimeError("database restarting")

    await Scheduler(tick, poll_interval=1).run_once()
    assert "Scheduler tick failed" in caplog.text


async def test_loop_keeps_ticking_after_a_failure_and_stops_promptly() -> None:
    calls = 0
    third_tick = asyncio.Event()

    async def tick(_now: datetime) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient")
        if calls >= 3:
            third_tick.set()

    scheduler = Scheduler(tick, poll_interval=0.01)
    scheduler.start()
    assert scheduler.running
    await asyncio.wait_for(third_tick.wait(), timeout=2)
    await asyncio.wait_for(scheduler.stop(), timeout=2)
    assert not scheduler.running
    assert calls >= 3


async def test_stop_interrupts_the_poll_sleep() -> None:
    ticked = asyncio.Event()

    async def tick(_now: datetime) -> None:
        ticked.set()

    # A one-hour poll interval: stop() must not wait for it.
    scheduler = Scheduler(tick, poll_interval=3600)
    scheduler.start()
    await asyncio.wait_for(ticked.wait(), timeout=2)
    await asyncio.wait_for(scheduler.stop(), timeout=2)
    assert not scheduler.running


async def test_start_twice_runs_a_single_loop() -> None:
    calls = 0
    ticked = asyncio.Event()

    async def tick(_now: datetime) -> None:
        nonlocal calls
        calls += 1
        ticked.set()

    scheduler = Scheduler(tick, poll_interval=3600)
    scheduler.start()
    scheduler.start()
    await asyncio.wait_for(ticked.wait(), timeout=2)
    await asyncio.sleep(0.05)
    await scheduler.stop()
    assert calls == 1


async def test_stop_without_start_is_a_no_op() -> None:
    async def tick(_now: datetime) -> None:
        return None

    await Scheduler(tick, poll_interval=1).stop()
