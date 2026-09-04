"""Regressions for engine initialization and bounded session bookkeeping."""

import importlib
from collections import Counter
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import ArgumentError

from app.cli import run_history, run_monitor
from app.core.config import settings
from app.detection.engine import MonitoringEvent, MonitoringEventType
from tests.unit.test_cli_persist import _make_snapshot


@pytest.mark.parametrize("command", ["history", "monitor"])
@pytest.mark.parametrize(
    "error", [ArgumentError("invalid URL"), ImportError("driver missing")]
)
async def test_engine_initialization_failure_returns_error(
    command, error, monkeypatch, capsys
):
    monkeypatch.setattr(settings, "DATABASE_URL", "configured")
    with patch("app.db.session.get_engine", side_effect=error) as get_engine:
        with patch("app.cli.monitor_host") as monitor:
            if command == "history":
                result = await run_history(None, 1, 10)
            else:
                result = await run_monitor("127.0.0.1", [80], 1, 1, True)
            assert result == 1
            get_engine.assert_called_once()
            monitor.assert_not_called()
    assert "error:" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["history", "monitor"])
async def test_real_malformed_url_is_handled(command, monkeypatch, capsys):
    db = importlib.import_module("app.db.session")
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(settings, "DATABASE_URL", "not-a-database-url")
    if command == "history":
        result = await run_history(None, 1, 10)
    else:
        result = await run_monitor("127.0.0.1", [80], 1, 1, True)
    assert result == 1
    assert db._engine is None
    assert "error:" in capsys.readouterr().err


@pytest.mark.parametrize("persist", [False, True])
async def test_monitor_retains_counts_not_event_history(persist, monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", "configured")
    snapshot = _make_snapshot()
    event = MonitoringEvent(
        event_type=MonitoringEventType.PORT_OPENED,
        target=snapshot.target,
        timestamp=snapshot.scan_result.started_at,
        port=80,
    )

    async def snapshots(**kwargs):
        for _ in range(150):
            yield snapshot

    engine = MagicMock(dispose=AsyncMock())
    service = MagicMock(persist_cycle=AsyncMock())
    with (
        patch("app.cli.monitor_host", side_effect=snapshots),
        patch("app.cli.detect_changes", return_value=[event]),
        patch("app.cli.format_snapshot"),
        patch("app.cli.format_monitoring_events"),
        patch("app.cli.format_session_summary") as summary,
        patch("app.db.session.get_engine", return_value=engine),
        patch("app.db.session.get_db_session", return_value=AsyncMock()),
        patch(
            "app.services.monitoring_persistence.MonitoringPersistenceService",
            return_value=service,
        ),
    ):
        assert await run_monitor("127.0.0.1", [80], 1, 150, persist) == 0
    counts = summary.call_args.args[2]
    assert isinstance(counts, Counter)
    assert counts == {MonitoringEventType.PORT_OPENED: 149}
    if persist:
        assert service.persist_cycle.await_count == 150
        engine.dispose.assert_awaited_once()
    else:
        engine.dispose.assert_not_awaited()


async def test_control_characters_never_reach_monitor_output(capsys):
    assert await run_monitor("fe80::1%scope\x1b[2J", [80], 1, 1, False) == 2
    captured = capsys.readouterr()
    assert "\x1b" not in captured.out + captured.err
