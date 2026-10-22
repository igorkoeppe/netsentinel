"""The API lifespan starts the scan scheduler only when explicitly enabled."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from app.core.config import settings
from app.main import app, lifespan


async def test_scheduler_not_started_by_default() -> None:
    with (
        patch.object(settings, "SCHEDULER_ENABLED", False),
        patch("app.main.create_scan_scheduler") as factory,
    ):
        async with lifespan(app):
            pass
    factory.assert_not_called()


async def test_scheduler_needs_database_url() -> None:
    with (
        patch.object(settings, "SCHEDULER_ENABLED", True),
        patch.object(settings, "DATABASE_URL", ""),
        patch("app.main.create_scan_scheduler") as factory,
    ):
        async with lifespan(app):
            pass
    factory.assert_not_called()


async def test_scheduler_started_and_stopped_with_the_app() -> None:
    scheduler = MagicMock()
    scheduler.stop = AsyncMock()
    with (
        patch.object(settings, "SCHEDULER_ENABLED", True),
        patch.object(settings, "DATABASE_URL", "postgresql+asyncpg://x/y"),
        patch("app.main.create_scan_scheduler", return_value=scheduler),
        patch("app.main.dispose_engine", new_callable=AsyncMock) as dispose,
    ):
        async with lifespan(app):
            scheduler.start.assert_called_once()
            scheduler.stop.assert_not_awaited()
    scheduler.stop.assert_awaited_once()
    dispose.assert_awaited_once()
