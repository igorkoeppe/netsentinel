"""Unit tests for the CLI alerts command."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from app.cli import (
    main,
    parse_alert_id,
    parse_alert_severity,
    parse_alert_status,
    run_acknowledge_alert,
    run_alerts,
    run_resolve_alert,
)
from app.core.config import settings
from app.detection.alerts import AlertStatus, InvalidAlertTransitionError, Severity
from app.models.security_alert import SecurityAlertRecord
from app.services.alert_query import AlertListItem
from app.services.alert_triage import AlertNotFoundError

_NOW = datetime(2026, 9, 8, 15, 30, 0, tzinfo=UTC)


def _make_item(
    *,
    alert_id: int = 42,
    severity: str = "high",
    alert_type: str = "unexpected_open_port",
    status: str = "OPEN",
    target: str = "127.0.0.1",
    port: int | None = 8080,
    created_at: datetime = _NOW,
    acknowledged_at: datetime | None = None,
    resolved_at: datetime | None = None,
) -> AlertListItem:
    return AlertListItem(
        id=alert_id,
        severity=severity,
        alert_type=alert_type,
        status=status,
        target=target,
        port=port,
        created_at=created_at,
        acknowledged_at=acknowledged_at,
        resolved_at=resolved_at,
    )


def _make_record(
    *,
    alert_id: int = 42,
    status: str = "ACKNOWLEDGED",
    acknowledged_at: datetime | None = None,
    resolved_at: datetime | None = None,
) -> SecurityAlertRecord:
    rec = MagicMock(spec=SecurityAlertRecord)
    rec.id = alert_id
    rec.status = status
    rec.acknowledged_at = acknowledged_at
    rec.resolved_at = resolved_at
    return rec


class TestParseAlertId:
    def test_valid_alert_id(self) -> None:
        assert parse_alert_id("42") == 42
        assert parse_alert_id("1") == 1

    def test_invalid_string(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError, match="Invalid alert ID: 'abc'"):
            parse_alert_id("abc")

    def test_zero_alert_id(self) -> None:
        with pytest.raises(
            argparse.ArgumentTypeError,
            match="Alert ID must be strictly positive",
        ):
            parse_alert_id("0")

    def test_negative_alert_id(self) -> None:
        with pytest.raises(
            argparse.ArgumentTypeError,
            match="Alert ID must be strictly positive",
        ):
            parse_alert_id("-1")


class TestParseAlertStatus:
    def test_valid_open(self) -> None:
        assert parse_alert_status("OPEN") == AlertStatus.OPEN
        assert parse_alert_status("open") == AlertStatus.OPEN
        assert parse_alert_status("Open") == AlertStatus.OPEN

    def test_valid_acknowledged(self) -> None:
        assert parse_alert_status("ACKNOWLEDGED") == AlertStatus.ACKNOWLEDGED
        assert parse_alert_status("acknowledged") == AlertStatus.ACKNOWLEDGED
        assert parse_alert_status("Acknowledged") == AlertStatus.ACKNOWLEDGED

    def test_valid_resolved(self) -> None:
        assert parse_alert_status("RESOLVED") == AlertStatus.RESOLVED
        assert parse_alert_status("resolved") == AlertStatus.RESOLVED
        assert parse_alert_status("Resolved") == AlertStatus.RESOLVED

    def test_invalid_status_closed(self) -> None:
        with pytest.raises(
            argparse.ArgumentTypeError,
            match="Invalid status 'CLOSED'.*",
        ):
            parse_alert_status("CLOSED")

    def test_invalid_status_banana(self) -> None:
        with pytest.raises(
            argparse.ArgumentTypeError,
            match="Invalid status 'banana'",
        ):
            parse_alert_status("banana")

    def test_invalid_status_empty(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError):
            parse_alert_status("")


class TestParseAlertSeverity:
    def test_valid_high(self) -> None:
        assert parse_alert_severity("HIGH") == Severity.HIGH
        assert parse_alert_severity("high") == Severity.HIGH
        assert parse_alert_severity("High") == Severity.HIGH

    def test_valid_severities(self) -> None:
        assert parse_alert_severity("info") == Severity.INFO
        assert parse_alert_severity("low") == Severity.LOW
        assert parse_alert_severity("medium") == Severity.MEDIUM
        assert parse_alert_severity("critical") == Severity.CRITICAL

    def test_invalid_severity_extreme(self) -> None:
        with pytest.raises(
            argparse.ArgumentTypeError,
            match="Invalid severity 'EXTREME'.*",
        ):
            parse_alert_severity("EXTREME")

    def test_invalid_severity_banana(self) -> None:
        with pytest.raises(
            argparse.ArgumentTypeError,
            match="Invalid severity 'banana'",
        ):
            parse_alert_severity("banana")

    def test_invalid_severity_empty(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError):
            parse_alert_severity("")


class TestRunAlerts:
    @pytest.fixture(autouse=True)
    def setup_db_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "DATABASE_URL", "postgresql+asyncpg://mock")

    async def test_no_db_url(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(settings, "DATABASE_URL", "")
        code = await run_alerts(20)
        assert code == 1
        captured = capsys.readouterr()
        assert "error: DATABASE_URL is required for alert queries" in captured.err

    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.alert_query.AlertQueryService")
    async def test_db_connection_failure(
        self,
        mock_svc_cls: MagicMock,
        mock_get_session: MagicMock,
        mock_get_engine: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__.side_effect = OperationalError("fake", {}, None)
        mock_get_session.return_value = mock_session_ctx

        code = await run_alerts(20)
        assert code == 1
        captured = capsys.readouterr()
        assert "error: could not connect to PostgreSQL database" in captured.err
        assert "fake" not in captured.err
        mock_engine.dispose.assert_awaited_once()

    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.alert_query.AlertQueryService")
    async def test_unexpected_failure(
        self,
        mock_svc_cls: MagicMock,
        mock_get_session: MagicMock,
        mock_get_engine: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__.side_effect = RuntimeError("Something unexpected")
        mock_get_session.return_value = mock_session_ctx

        code = await run_alerts(20)
        assert code == 1
        captured = capsys.readouterr()
        assert "error: unexpected failure: Something unexpected" in captured.err
        mock_engine.dispose.assert_awaited_once()

    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.alert_query.AlertQueryService")
    async def test_empty_alerts(
        self,
        mock_svc_cls: MagicMock,
        mock_get_session: MagicMock,
        mock_get_engine: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        mock_session = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__.return_value = mock_session
        mock_get_session.return_value = mock_session_ctx

        mock_svc = AsyncMock()
        mock_svc.list_alerts.return_value = []
        mock_svc_cls.return_value = mock_svc

        code = await run_alerts(20)
        assert code == 0
        captured = capsys.readouterr()
        assert "No security alerts found." in captured.out
        assert "[]" not in captured.out
        mock_svc.list_alerts.assert_awaited_once_with(
            limit=20, status=None, severity=None
        )
        mock_engine.dispose.assert_awaited_once()

    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.alert_query.AlertQueryService")
    async def test_single_open_alert(
        self,
        mock_svc_cls: MagicMock,
        mock_get_session: MagicMock,
        mock_get_engine: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__.return_value = AsyncMock()
        mock_get_session.return_value = mock_session_ctx

        item = _make_item(
            alert_id=42,
            severity="high",
            alert_type="unexpected_open_port",
            status="OPEN",
            target="127.0.0.1",
            port=8080,
        )
        mock_svc = AsyncMock()
        mock_svc.list_alerts.return_value = [item]
        mock_svc_cls.return_value = mock_svc

        code = await run_alerts(20)
        assert code == 0
        captured = capsys.readouterr()
        assert "NetSentinel Security Alerts" in captured.out
        assert "ID" in captured.out
        assert "SEVERITY" in captured.out
        assert "TYPE" in captured.out
        assert "STATUS" in captured.out
        assert "TARGET" in captured.out
        assert "PORT" in captured.out
        assert "CREATED" in captured.out
        assert "42" in captured.out
        assert "HIGH" in captured.out
        assert "UNEXPECTED_OPEN_PORT" in captured.out
        assert "OPEN" in captured.out
        assert "127.0.0.1" in captured.out
        assert "8080" in captured.out

    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.alert_query.AlertQueryService")
    async def test_acknowledged_alert(
        self,
        mock_svc_cls: MagicMock,
        mock_get_session: MagicMock,
        mock_get_engine: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__.return_value = AsyncMock()
        mock_get_session.return_value = mock_session_ctx

        item = _make_item(
            alert_id=41,
            severity="low",
            alert_type="port_closed",
            status="ACKNOWLEDGED",
            target="127.0.0.1",
            port=22,
        )
        mock_svc = AsyncMock()
        mock_svc.list_alerts.return_value = [item]
        mock_svc_cls.return_value = mock_svc

        code = await run_alerts(20)
        assert code == 0
        captured = capsys.readouterr()
        assert "ACKNOWLEDGED" in captured.out
        assert "PORT_CLOSED" in captured.out
        assert "LOW" in captured.out

    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.alert_query.AlertQueryService")
    async def test_resolved_alert(
        self,
        mock_svc_cls: MagicMock,
        mock_get_session: MagicMock,
        mock_get_engine: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__.return_value = AsyncMock()
        mock_get_session.return_value = mock_session_ctx

        item = _make_item(
            alert_id=40,
            severity="medium",
            alert_type="host_down",
            status="RESOLVED",
            target="127.0.0.1",
            port=None,
        )
        mock_svc = AsyncMock()
        mock_svc.list_alerts.return_value = [item]
        mock_svc_cls.return_value = mock_svc

        code = await run_alerts(20)
        assert code == 0
        captured = capsys.readouterr()
        assert "RESOLVED" in captured.out
        assert "HOST_DOWN" in captured.out
        assert "MEDIUM" in captured.out

    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.alert_query.AlertQueryService")
    async def test_alert_without_port_displays_dash(
        self,
        mock_svc_cls: MagicMock,
        mock_get_session: MagicMock,
        mock_get_engine: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__.return_value = AsyncMock()
        mock_get_session.return_value = mock_session_ctx

        item = _make_item(alert_id=1, port=None, alert_type="host_down")
        mock_svc = AsyncMock()
        mock_svc.list_alerts.return_value = [item]
        mock_svc_cls.return_value = mock_svc

        code = await run_alerts(20)
        assert code == 0
        captured = capsys.readouterr()
        assert "None" not in captured.out
        lines = captured.out.strip().split("\n")
        data_line = [line for line in lines if "1" in line and "HOST_DOWN" in line][0]
        assert "-" in data_line

    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.alert_query.AlertQueryService")
    async def test_multiple_severities(
        self,
        mock_svc_cls: MagicMock,
        mock_get_session: MagicMock,
        mock_get_engine: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__.return_value = AsyncMock()
        mock_get_session.return_value = mock_session_ctx

        items = [
            _make_item(alert_id=1, severity="info"),
            _make_item(alert_id=2, severity="low"),
            _make_item(alert_id=3, severity="medium"),
            _make_item(alert_id=4, severity="high"),
            _make_item(alert_id=5, severity="critical"),
        ]
        mock_svc = AsyncMock()
        mock_svc.list_alerts.return_value = items
        mock_svc_cls.return_value = mock_svc

        code = await run_alerts(20)
        assert code == 0
        captured = capsys.readouterr()
        assert "INFO" in captured.out
        assert "LOW" in captured.out
        assert "MEDIUM" in captured.out
        assert "HIGH" in captured.out
        assert "CRITICAL" in captured.out

    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.alert_query.AlertQueryService")
    async def test_ordering_preserved(
        self,
        mock_svc_cls: MagicMock,
        mock_get_session: MagicMock,
        mock_get_engine: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__.return_value = AsyncMock()
        mock_get_session.return_value = mock_session_ctx

        newer = _make_item(alert_id=10, created_at=_NOW + timedelta(minutes=10))
        older = _make_item(alert_id=9, created_at=_NOW)
        mock_svc = AsyncMock()
        mock_svc.list_alerts.return_value = [newer, older]
        mock_svc_cls.return_value = mock_svc

        code = await run_alerts(20)
        assert code == 0
        captured = capsys.readouterr()
        pos_newer = captured.out.find("10")
        pos_older = captured.out.find("9")
        assert pos_newer < pos_older


class TestRunAcknowledgeAlert:
    @pytest.fixture(autouse=True)
    def setup_db_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "DATABASE_URL", "postgresql+asyncpg://mock")

    async def test_no_db_url(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(settings, "DATABASE_URL", "")
        code = await run_acknowledge_alert(42)
        assert code == 1
        captured = capsys.readouterr()
        assert "error: DATABASE_URL is required for alert operations" in captured.err

    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.alert_triage.AlertTriageService")
    async def test_acknowledge_success(
        self,
        mock_svc_cls: MagicMock,
        mock_get_session: MagicMock,
        mock_get_engine: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__.return_value = AsyncMock()
        mock_get_session.return_value = mock_session_ctx

        ack_time = _NOW
        rec = _make_record(
            alert_id=42,
            status="ACKNOWLEDGED",
            acknowledged_at=ack_time,
        )
        mock_svc = AsyncMock()
        mock_svc.acknowledge.return_value = rec
        mock_svc_cls.return_value = mock_svc

        code = await run_acknowledge_alert(42)
        assert code == 0
        captured = capsys.readouterr()
        assert "Alert 42 acknowledged." in captured.out
        assert "Status: ACKNOWLEDGED" in captured.out
        assert f"Acknowledged at: {ack_time}" in captured.out

        mock_svc.acknowledge.assert_awaited_once()
        call_kwargs = mock_svc.acknowledge.await_args
        assert call_kwargs.args[0] == 42
        assert call_kwargs.kwargs["at"] is not None
        assert call_kwargs.kwargs["at"].tzinfo is not None
        mock_engine.dispose.assert_awaited_once()

    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.alert_triage.AlertTriageService")
    async def test_acknowledge_not_found(
        self,
        mock_svc_cls: MagicMock,
        mock_get_session: MagicMock,
        mock_get_engine: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__.return_value = AsyncMock()
        mock_get_session.return_value = mock_session_ctx

        mock_svc = AsyncMock()
        mock_svc.acknowledge.side_effect = AlertNotFoundError(999)
        mock_svc_cls.return_value = mock_svc

        code = await run_acknowledge_alert(999)
        assert code == 1
        captured = capsys.readouterr()
        assert "Alert 999 not found." in captured.err
        mock_engine.dispose.assert_awaited_once()

    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.alert_triage.AlertTriageService")
    async def test_acknowledge_invalid_transition(
        self,
        mock_svc_cls: MagicMock,
        mock_get_session: MagicMock,
        mock_get_engine: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__.return_value = AsyncMock()
        mock_get_session.return_value = mock_session_ctx

        mock_svc = AsyncMock()
        mock_svc.acknowledge.side_effect = InvalidAlertTransitionError(
            AlertStatus.RESOLVED,
            AlertStatus.ACKNOWLEDGED,
        )
        mock_svc_cls.return_value = mock_svc

        code = await run_acknowledge_alert(42)
        assert code == 1
        captured = capsys.readouterr()
        assert (
            "Cannot transition alert 42 from RESOLVED to ACKNOWLEDGED" in captured.err
        )
        mock_engine.dispose.assert_awaited_once()

    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.alert_triage.AlertTriageService")
    async def test_acknowledge_already_acknowledged(
        self,
        mock_svc_cls: MagicMock,
        mock_get_session: MagicMock,
        mock_get_engine: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__.return_value = AsyncMock()
        mock_get_session.return_value = mock_session_ctx

        mock_svc = AsyncMock()
        mock_svc.acknowledge.side_effect = InvalidAlertTransitionError(
            AlertStatus.ACKNOWLEDGED,
            AlertStatus.ACKNOWLEDGED,
        )
        mock_svc_cls.return_value = mock_svc

        code = await run_acknowledge_alert(42)
        assert code == 1
        captured = capsys.readouterr()
        assert "Alert 42 is already in ACKNOWLEDGED status." in captured.err
        mock_engine.dispose.assert_awaited_once()

    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.alert_triage.AlertTriageService")
    async def test_acknowledge_db_connection_failure(
        self,
        mock_svc_cls: MagicMock,
        mock_get_session: MagicMock,
        mock_get_engine: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__.side_effect = OperationalError("fake", {}, None)
        mock_get_session.return_value = mock_session_ctx

        code = await run_acknowledge_alert(42)
        assert code == 1
        captured = capsys.readouterr()
        assert "error: could not connect to PostgreSQL database" in captured.err
        mock_engine.dispose.assert_awaited_once()

    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.alert_triage.AlertTriageService")
    async def test_acknowledge_unexpected_failure(
        self,
        mock_svc_cls: MagicMock,
        mock_get_session: MagicMock,
        mock_get_engine: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__.side_effect = RuntimeError("DB exploded")
        mock_get_session.return_value = mock_session_ctx

        code = await run_acknowledge_alert(42)
        assert code == 1
        captured = capsys.readouterr()
        assert "error: unexpected failure: DB exploded" in captured.err
        mock_engine.dispose.assert_awaited_once()


class TestRunResolveAlert:
    @pytest.fixture(autouse=True)
    def setup_db_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "DATABASE_URL", "postgresql+asyncpg://mock")

    async def test_no_db_url(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(settings, "DATABASE_URL", "")
        code = await run_resolve_alert(42)
        assert code == 1
        captured = capsys.readouterr()
        assert "error: DATABASE_URL is required for alert operations" in captured.err

    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.alert_triage.AlertTriageService")
    async def test_resolve_from_open_success(
        self,
        mock_svc_cls: MagicMock,
        mock_get_session: MagicMock,
        mock_get_engine: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__.return_value = AsyncMock()
        mock_get_session.return_value = mock_session_ctx

        res_time = _NOW
        rec = _make_record(
            alert_id=42,
            status="RESOLVED",
            acknowledged_at=None,
            resolved_at=res_time,
        )
        mock_svc = AsyncMock()
        mock_svc.resolve.return_value = rec
        mock_svc_cls.return_value = mock_svc

        code = await run_resolve_alert(42)
        assert code == 0
        captured = capsys.readouterr()
        assert "Alert 42 resolved." in captured.out
        assert "Status: RESOLVED" in captured.out
        assert f"Resolved at: {res_time}" in captured.out
        assert "Acknowledged at:" not in captured.out

        mock_svc.resolve.assert_awaited_once()
        call_kwargs = mock_svc.resolve.await_args
        assert call_kwargs.args[0] == 42
        assert call_kwargs.kwargs["at"] is not None
        assert call_kwargs.kwargs["at"].tzinfo is not None
        mock_engine.dispose.assert_awaited_once()

    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.alert_triage.AlertTriageService")
    async def test_resolve_from_acknowledged_success(
        self,
        mock_svc_cls: MagicMock,
        mock_get_session: MagicMock,
        mock_get_engine: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__.return_value = AsyncMock()
        mock_get_session.return_value = mock_session_ctx

        ack_time = _NOW
        res_time = _NOW + timedelta(minutes=15)
        rec = _make_record(
            alert_id=42,
            status="RESOLVED",
            acknowledged_at=ack_time,
            resolved_at=res_time,
        )
        mock_svc = AsyncMock()
        mock_svc.resolve.return_value = rec
        mock_svc_cls.return_value = mock_svc

        code = await run_resolve_alert(42)
        assert code == 0
        captured = capsys.readouterr()
        assert "Alert 42 resolved." in captured.out
        assert "Status: RESOLVED" in captured.out
        assert f"Acknowledged at: {ack_time}" in captured.out
        assert f"Resolved at: {res_time}" in captured.out
        mock_engine.dispose.assert_awaited_once()

    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.alert_triage.AlertTriageService")
    async def test_resolve_not_found(
        self,
        mock_svc_cls: MagicMock,
        mock_get_session: MagicMock,
        mock_get_engine: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__.return_value = AsyncMock()
        mock_get_session.return_value = mock_session_ctx

        mock_svc = AsyncMock()
        mock_svc.resolve.side_effect = AlertNotFoundError(999)
        mock_svc_cls.return_value = mock_svc

        code = await run_resolve_alert(999)
        assert code == 1
        captured = capsys.readouterr()
        assert "Alert 999 not found." in captured.err
        mock_engine.dispose.assert_awaited_once()

    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.alert_triage.AlertTriageService")
    async def test_resolve_already_resolved(
        self,
        mock_svc_cls: MagicMock,
        mock_get_session: MagicMock,
        mock_get_engine: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__.return_value = AsyncMock()
        mock_get_session.return_value = mock_session_ctx

        mock_svc = AsyncMock()
        mock_svc.resolve.side_effect = InvalidAlertTransitionError(
            AlertStatus.RESOLVED,
            AlertStatus.RESOLVED,
        )
        mock_svc_cls.return_value = mock_svc

        code = await run_resolve_alert(42)
        assert code == 1
        captured = capsys.readouterr()
        assert "Alert 42 is already in RESOLVED status." in captured.err
        mock_engine.dispose.assert_awaited_once()

    @patch("app.db.session.get_engine")
    @patch("app.db.session.get_db_session")
    @patch("app.services.alert_triage.AlertTriageService")
    async def test_resolve_db_failure(
        self,
        mock_svc_cls: MagicMock,
        mock_get_session: MagicMock,
        mock_get_engine: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__.side_effect = OperationalError("fake", {}, None)
        mock_get_session.return_value = mock_session_ctx

        code = await run_resolve_alert(42)
        assert code == 1
        captured = capsys.readouterr()
        assert "error: could not connect to PostgreSQL database" in captured.err
        mock_engine.dispose.assert_awaited_once()


class TestCliAlertsMain:
    @patch("app.cli.run_alerts")
    def test_main_alerts_default_limit(self, mock_run_alerts: MagicMock) -> None:
        mock_run_alerts.return_value = 0
        with patch.object(sys, "argv", ["netsentinel", "alerts"]):
            code = main()
            assert code == 0
            mock_run_alerts.assert_called_once_with(
                limit=20, status=None, severity=None
            )

    @patch("app.cli.run_alerts")
    def test_main_alerts_custom_limit(self, mock_run_alerts: MagicMock) -> None:
        mock_run_alerts.return_value = 0
        with patch.object(sys, "argv", ["netsentinel", "alerts", "--limit", "5"]):
            code = main()
            assert code == 0
            mock_run_alerts.assert_called_once_with(limit=5, status=None, severity=None)

    @patch("app.cli.run_alerts")
    def test_main_alerts_status_filter(self, mock_run_alerts: MagicMock) -> None:
        mock_run_alerts.return_value = 0
        with patch.object(sys, "argv", ["netsentinel", "alerts", "--status", "OPEN"]):
            code = main()
            assert code == 0
            mock_run_alerts.assert_called_once_with(
                limit=20, status=AlertStatus.OPEN, severity=None
            )

    @patch("app.cli.run_alerts")
    def test_main_alerts_status_case_insensitive(
        self, mock_run_alerts: MagicMock
    ) -> None:
        mock_run_alerts.return_value = 0
        with patch.object(sys, "argv", ["netsentinel", "alerts", "--status", "open"]):
            code = main()
            assert code == 0
            mock_run_alerts.assert_called_once_with(
                limit=20, status=AlertStatus.OPEN, severity=None
            )

    @patch("app.cli.run_alerts")
    def test_main_alerts_severity_filter(self, mock_run_alerts: MagicMock) -> None:
        mock_run_alerts.return_value = 0
        with patch.object(sys, "argv", ["netsentinel", "alerts", "--severity", "HIGH"]):
            code = main()
            assert code == 0
            mock_run_alerts.assert_called_once_with(
                limit=20, status=None, severity=Severity.HIGH
            )

    @patch("app.cli.run_alerts")
    def test_main_alerts_severity_case_insensitive(
        self, mock_run_alerts: MagicMock
    ) -> None:
        mock_run_alerts.return_value = 0
        with patch.object(sys, "argv", ["netsentinel", "alerts", "--severity", "high"]):
            code = main()
            assert code == 0
            mock_run_alerts.assert_called_once_with(
                limit=20, status=None, severity=Severity.HIGH
            )

    @patch("app.cli.run_alerts")
    def test_main_alerts_combined_filters(self, mock_run_alerts: MagicMock) -> None:
        mock_run_alerts.return_value = 0
        with patch.object(
            sys,
            "argv",
            [
                "netsentinel",
                "alerts",
                "--status",
                "OPEN",
                "--severity",
                "HIGH",
                "--limit",
                "5",
            ],
        ):
            code = main()
            assert code == 0
            mock_run_alerts.assert_called_once_with(
                limit=5, status=AlertStatus.OPEN, severity=Severity.HIGH
            )

    def test_main_alerts_invalid_status(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch.object(sys, "argv", ["netsentinel", "alerts", "--status", "CLOSED"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2
            captured = capsys.readouterr()
            assert "Invalid status 'CLOSED'" in captured.err

    def test_main_alerts_invalid_status_banana(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch.object(sys, "argv", ["netsentinel", "alerts", "--status", "banana"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2
            captured = capsys.readouterr()
            assert "Invalid status 'banana'" in captured.err

    def test_main_alerts_invalid_severity(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch.object(
            sys, "argv", ["netsentinel", "alerts", "--severity", "EXTREME"]
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2
            captured = capsys.readouterr()
            assert "Invalid severity 'EXTREME'" in captured.err

    def test_main_alerts_invalid_severity_extreme_lower(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch.object(
            sys, "argv", ["netsentinel", "alerts", "--severity", "extreme"]
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2
            captured = capsys.readouterr()
            assert "Invalid severity 'extreme'" in captured.err

    def test_main_acknowledge_rejects_status_flag(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch.object(
            sys,
            "argv",
            ["netsentinel", "alerts", "acknowledge", "42", "--status", "OPEN"],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2
            captured = capsys.readouterr()
            assert "unrecognized arguments: --status" in captured.err

    @patch("app.cli.run_acknowledge_alert")
    def test_main_alerts_acknowledge_dispatch(self, mock_run_ack: MagicMock) -> None:
        mock_run_ack.return_value = 0
        with patch.object(sys, "argv", ["netsentinel", "alerts", "acknowledge", "42"]):
            code = main()
            assert code == 0
            mock_run_ack.assert_called_once_with(42)

    @patch("app.cli.run_resolve_alert")
    def test_main_alerts_resolve_dispatch(self, mock_run_res: MagicMock) -> None:
        mock_run_res.return_value = 0
        with patch.object(sys, "argv", ["netsentinel", "alerts", "resolve", "42"]):
            code = main()
            assert code == 0
            mock_run_res.assert_called_once_with(42)

    def test_main_alerts_invalid_limit_zero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch.object(sys, "argv", ["netsentinel", "alerts", "--limit", "0"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2
            captured = capsys.readouterr()
            assert "Limit must be strictly positive" in captured.err

    def test_main_alerts_invalid_limit_negative(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch.object(sys, "argv", ["netsentinel", "alerts", "--limit", "-1"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2
            captured = capsys.readouterr()
            assert "Limit must be strictly positive" in captured.err

    def test_main_alerts_invalid_limit_string(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch.object(sys, "argv", ["netsentinel", "alerts", "--limit", "abc"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2
            captured = capsys.readouterr()
            assert "Invalid limit: 'abc'" in captured.err

    def test_main_acknowledge_invalid_id_zero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch.object(sys, "argv", ["netsentinel", "alerts", "acknowledge", "0"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2
            captured = capsys.readouterr()
            assert "Alert ID must be strictly positive" in captured.err

    def test_main_acknowledge_invalid_id_negative(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch.object(sys, "argv", ["netsentinel", "alerts", "acknowledge", "-1"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2
            captured = capsys.readouterr()
            assert "Alert ID must be strictly positive" in captured.err

    def test_main_acknowledge_invalid_id_string(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch.object(sys, "argv", ["netsentinel", "alerts", "acknowledge", "abc"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2
            captured = capsys.readouterr()
            assert "Invalid alert ID: 'abc'" in captured.err

    def test_main_resolve_invalid_id_zero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch.object(sys, "argv", ["netsentinel", "alerts", "resolve", "0"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2
            captured = capsys.readouterr()
            assert "Alert ID must be strictly positive" in captured.err
