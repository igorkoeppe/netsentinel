"""In-process asyncio scheduler for periodic work.

The scheduler only knows *when* to run: every ``poll_interval`` seconds it
calls ``tick(now)``. What a tick does (claim due scan schedules, run them,
persist results) lives in :mod:`app.services.scheduled_scan`, so this module
has no database or network dependency and is trivial to test.

Design notes:
- one background task, started and stopped explicitly (FastAPI lifespan or the
  ``netsentinel schedule run`` command);
- ticks never overlap: the next poll waits for the current tick to finish;
- an exception in a tick is logged and the loop keeps going, so one bad cycle
  (for example the database restarting) does not silently stop scheduling;
- ``stop()`` wakes the loop immediately instead of waiting for the sleep.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

TickFunction = Callable[[datetime], Awaitable[object]]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Scheduler:
    """Run ``tick`` periodically in a single asyncio task."""

    def __init__(
        self,
        tick: TickFunction,
        *,
        poll_interval: float,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        if poll_interval <= 0:
            raise ValueError(
                f"poll_interval must be strictly positive, got {poll_interval}"
            )
        self._tick = tick
        self._poll_interval = poll_interval
        self._clock = clock
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def run_once(self) -> None:
        """Execute a single tick, logging (not raising) any failure."""
        try:
            await self._tick(self._clock())
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduler tick failed; retrying on next poll")

    async def run_forever(self) -> None:
        """Tick until :meth:`stop` is called."""
        while not self._stop_event.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._poll_interval
                )
            except TimeoutError:
                continue

    def start(self) -> None:
        """Start the background task. Calling it twice is a no-op."""
        if self.running:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self.run_forever(), name="netsentinel-scheduler"
        )
        logger.info("Scheduler started (poll interval %ss)", self._poll_interval)

    async def stop(self) -> None:
        """Ask the loop to stop and wait for the current tick to finish."""
        self._stop_event.set()
        task, self._task = self._task, None
        if task is not None:
            await task
            logger.info("Scheduler stopped")
