"""Unit tests for the `netsentinel schedule` CLI commands."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.cli import (
    format_scheduled_run,
    format_schedules_table,
    main,
    run_schedule_add,
    run_schedule_update,
    run_scheduler,
)
from app.core.config import settings
from app.detection.alerts import AlertType, SecurityAlert, Severity
from app.monitoring.target import NetworkTarget
from app.services.scan_schedule import (
    DEFAULT_SCHEDULE_INTERVAL,
    InvalidScheduleError,
    ScheduleItem,
)
from app.services.scheduled_scan import ScheduledRunResult

_NOW = datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC)


def _item(**overrides: object) -> ScheduleItem:
    values: dict[str, object] = {
        "id": 1,
        "host_id": 1,
        "address": "127.0.0.1",
        "name": None,
        "ports": (22, 80),
        "interval_seconds": 300,
        "enabled": True,
        "next_run_at": _NOW,
        "last_run_at": None,
        "last_scan_id": None,
        "last_error": None,
        "created_at": _NOW,
        "updated_at": None,
    }
    values.update(overrides)
    return ScheduleItem(**values)  # type: ignore[arg-type]


def _run_main(argv: list[str]) -> int:
    with patch.object(sys, "argv", ["netsentinel", *argv]):
        return main()


def test_schedule_add_routes_arguments() -> None:
    with patch("app.cli.run_schedule_add", new_callable=AsyncMock, return_value=0) as m:
        assert _run_main(["schedule", "add", "127.0.0.1", "--ports", "22,80"]) == 0
    m.assert_awaited_once_with("127.0.0.1", [22, 80], DEFAULT_SCHEDULE_INTERVAL, True)


def test_schedule_add_disabled_with_interval() -> None:
    with patch("app.cli.run_schedule_add", new_callable=AsyncMock, return_value=0) as m:
        _run_main(
            [
                "schedule",
                "add",
                "127.0.0.1",
                "--ports",
                "22",
                "--interval",
                "600",
                "--disabled",
            ]
        )
    m.assert_awaited_once_with("127.0.0.1", [22], 600, False)


@pytest.mark.parametrize(
    ("argv", "kwargs"),
    [
        (["schedule", "enable", "4"], {"enabled": True}),
        (["schedule", "disable", "4"], {"enabled": False}),
        (
            ["schedule", "update", "4", "--interval", "120"],
            {"ports": None, "interval": 120},
        ),
    ],
)
def test_schedule_update_commands(argv: list[str], kwargs: dict[str, object]) -> None:
    with patch(
        "app.cli.run_schedule_update", new_callable=AsyncMock, return_value=0
    ) as m:
        assert _run_main(argv) == 0
    m.assert_awaited_once_with(4, **kwargs)


def test_schedule_run_once_flag() -> None:
    with patch("app.cli.run_scheduler", new_callable=AsyncMock, return_value=0) as m:
        _run_main(["schedule", "run", "--once"])
    m.assert_awaited_once_with(True)


def test_schedule_requires_an_action() -> None:
    with pytest.raises(SystemExit):
        _run_main(["schedule"])


def test_schedule_rejects_invalid_id() -> None:
    with pytest.raises(SystemExit):
        _run_main(["schedule", "enable", "0"])


async def test_add_requires_database_url(capsys: pytest.CaptureFixture[str]) -> None:
    with patch.object(settings, "DATABASE_URL", ""):
        assert await run_schedule_add("127.0.0.1", [22], 300, True) == 1
    assert "DATABASE_URL is required" in capsys.readouterr().err


async def test_scheduler_requires_database_url(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with patch.object(settings, "DATABASE_URL", ""):
        assert await run_scheduler(once=True) == 1
    assert "DATABASE_URL is required" in capsys.readouterr().err


async def test_update_without_changes_is_rejected(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with patch.object(settings, "DATABASE_URL", "postgresql+asyncpg://x/y"):
        assert await run_schedule_update(1) == 2
    assert "nothing to update" in capsys.readouterr().err


async def test_add_reports_validation_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=AsyncMock())
    session_cm.__aexit__ = AsyncMock(return_value=False)
    engine = MagicMock()
    engine.dispose = AsyncMock()
    with (
        patch.object(settings, "DATABASE_URL", "postgresql+asyncpg://x/y"),
        patch("app.db.session.get_engine", return_value=engine),
        patch("app.db.session.get_db_session", return_value=session_cm),
        patch(
            "app.services.scan_schedule.ScanScheduleService.create_schedule",
            new_callable=AsyncMock,
            side_effect=InvalidScheduleError("Interval must be at least 60 seconds"),
        ),
    ):
        assert await run_schedule_add("127.0.0.1", [22], 10, True) == 2
    assert "at least 60" in capsys.readouterr().err
    engine.dispose.assert_awaited_once()


async def test_run_once_prints_each_result(capsys: pytest.CaptureFixture[str]) -> None:
    runner = MagicMock()
    runner.run_due = AsyncMock(
        return_value=[
            ScheduledRunResult(schedule_id=1, address="127.0.0.1", scan_id=10),
            ScheduledRunResult(schedule_id=2, address="10.0.0.9", error="boom"),
        ]
    )
    with (
        patch.object(settings, "DATABASE_URL", "postgresql+asyncpg://x/y"),
        patch(
            "app.services.scheduled_scan.create_scheduled_scan_runner",
            return_value=runner,
        ),
        patch("app.db.session.dispose_engine", new_callable=AsyncMock),
    ):
        assert await run_scheduler(once=True) == 0

    out = capsys.readouterr().out
    assert "schedule 1 127.0.0.1: scan 10, 0 change(s), 0 alert(s)" in out
    assert "schedule 2 10.0.0.9: FAILED (boom)" in out
    runner.run_due.assert_awaited_once()


def test_format_scheduled_run_lists_alerts(capsys: pytest.CaptureFixture[str]) -> None:
    alert = SecurityAlert(
        alert_type=AlertType.NEW_OPEN_PORT,
        severity=Severity.HIGH,
        target=NetworkTarget.parse("127.0.0.1"),
        timestamp=_NOW,
        message="New TCP port 8080 detected on 127.0.0.1.",
        port=8080,
        source_event_type="port_opened",
    )
    format_scheduled_run(
        ScheduledRunResult(
            schedule_id=1, address="127.0.0.1", scan_id=5, event_count=1, alerts=[alert]
        )
    )
    out = capsys.readouterr().out
    assert "1 change(s), 1 alert(s)" in out
    assert "NEW_OPEN_PORT" in out


def test_format_schedules_table(capsys: pytest.CaptureFixture[str]) -> None:
    format_schedules_table(
        [_item(), _item(id=2, enabled=False, last_run_at=_NOW, last_error="boom")]
    )
    out = capsys.readouterr().out
    assert "22,80" in out
    assert "last error: boom" in out

    format_schedules_table([])
    assert "No scan schedules found." in capsys.readouterr().out
