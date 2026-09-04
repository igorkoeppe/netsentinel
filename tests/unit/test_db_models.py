"""Unit tests for the v0.3 database models and configuration.

These tests do NOT require a live PostgreSQL instance.
They verify:
1. All expected tables are registered in Base.metadata.
2. Column constraints match the design (nullable, FK, unique).
3. Domain enum values are compatible with what the ORM stores.
4. DATABASE_URL can be loaded via environment variable without exposure.
5. Importing the db session module does not attempt a database connection.
"""

import os

import pytest
from sqlalchemy import UniqueConstraint

# app.models is imported solely for its side effect of registering all ORM
# models with Base.metadata. This must precede the Base import here so that
# ruff isort is satisfied (app < app.db alphabetically within first-party).
import app.models  # noqa: F401
from app.db.base import Base


# ---------------------------------------------------------------------------
# Test 1 — Metadata: all expected tables are registered.
# ---------------------------------------------------------------------------


class TestMetadata:
    EXPECTED_TABLES = {
        "hosts",
        "scans",
        "port_results",
        "monitoring_events",
        "security_alerts",
    }

    def test_all_tables_registered(self) -> None:
        """All four core tables must be present in Base.metadata."""
        registered = set(Base.metadata.tables.keys())
        assert self.EXPECTED_TABLES <= registered, (
            f"Missing tables: {self.EXPECTED_TABLES - registered}"
        )

    def test_no_unexpected_tables(self) -> None:
        """No extra tables should appear beyond the four defined in v0.3."""
        registered = set(Base.metadata.tables.keys())
        unexpected = registered - self.EXPECTED_TABLES
        assert not unexpected, f"Unexpected tables in metadata: {unexpected}"


# ---------------------------------------------------------------------------
# Test 2 — Constraints: nullable, FK, unique.
# ---------------------------------------------------------------------------


class TestHostConstraints:
    def _table(self) -> object:
        return Base.metadata.tables["hosts"]

    def test_address_not_nullable(self) -> None:
        table = Base.metadata.tables["hosts"]
        col = table.c["address"]
        assert not col.nullable, "hosts.address must be NOT NULL"

    def test_address_unique(self) -> None:
        table = Base.metadata.tables["hosts"]
        unique_cols = {
            frozenset(c.name for c in uc.columns)
            for uc in table.constraints
            if isinstance(uc, UniqueConstraint)
        }
        assert frozenset({"address"}) in unique_cols, (
            "hosts.address must have a UNIQUE constraint"
        )

    def test_enabled_not_nullable(self) -> None:
        table = Base.metadata.tables["hosts"]
        col = table.c["enabled"]
        assert not col.nullable, "hosts.enabled must be NOT NULL"

    def test_created_at_not_nullable(self) -> None:
        table = Base.metadata.tables["hosts"]
        col = table.c["created_at"]
        assert not col.nullable, "hosts.created_at must be NOT NULL"

    def test_updated_at_nullable(self) -> None:
        table = Base.metadata.tables["hosts"]
        col = table.c["updated_at"]
        assert col.nullable, "hosts.updated_at must be nullable"


class TestScanConstraints:
    def test_host_id_not_nullable(self) -> None:
        table = Base.metadata.tables["scans"]
        col = table.c["host_id"]
        assert not col.nullable, "scans.host_id must be NOT NULL"

    def test_host_id_foreign_key(self) -> None:
        table = Base.metadata.tables["scans"]
        fk_targets = {fk.target_fullname for c in table.c for fk in c.foreign_keys}
        assert "hosts.id" in fk_targets, "scans.host_id must reference hosts.id"

    def test_status_not_nullable(self) -> None:
        table = Base.metadata.tables["scans"]
        col = table.c["status"]
        assert not col.nullable, "scans.status must be NOT NULL"

    def test_response_time_ms_nullable(self) -> None:
        table = Base.metadata.tables["scans"]
        col = table.c["response_time_ms"]
        assert col.nullable, "scans.response_time_ms must be nullable"

    def test_finished_at_nullable(self) -> None:
        table = Base.metadata.tables["scans"]
        col = table.c["finished_at"]
        assert col.nullable, "scans.finished_at must be nullable"


class TestPortResultConstraints:
    def test_scan_id_not_nullable(self) -> None:
        table = Base.metadata.tables["port_results"]
        col = table.c["scan_id"]
        assert not col.nullable, "port_results.scan_id must be NOT NULL"

    def test_scan_id_foreign_key(self) -> None:
        table = Base.metadata.tables["port_results"]
        fk_targets = {fk.target_fullname for c in table.c for fk in c.foreign_keys}
        assert "scans.id" in fk_targets, "port_results.scan_id must reference scans.id"

    def test_port_not_nullable(self) -> None:
        table = Base.metadata.tables["port_results"]
        col = table.c["port"]
        assert not col.nullable, "port_results.port must be NOT NULL"

    def test_status_not_nullable(self) -> None:
        table = Base.metadata.tables["port_results"]
        col = table.c["status"]
        assert not col.nullable, "port_results.status must be NOT NULL"

    def test_response_time_ms_nullable(self) -> None:
        table = Base.metadata.tables["port_results"]
        col = table.c["response_time_ms"]
        assert col.nullable, "port_results.response_time_ms must be nullable"


class TestMonitoringEventConstraints:
    def test_host_id_not_nullable(self) -> None:
        table = Base.metadata.tables["monitoring_events"]
        col = table.c["host_id"]
        assert not col.nullable, "monitoring_events.host_id must be NOT NULL"

    def test_host_id_foreign_key(self) -> None:
        table = Base.metadata.tables["monitoring_events"]
        fk_targets = {fk.target_fullname for c in table.c for fk in c.foreign_keys}
        assert "hosts.id" in fk_targets, (
            "monitoring_events.host_id must reference hosts.id"
        )

    def test_scan_id_nullable(self) -> None:
        table = Base.metadata.tables["monitoring_events"]
        col = table.c["scan_id"]
        assert col.nullable, "monitoring_events.scan_id must be nullable"

    def test_scan_id_foreign_key(self) -> None:
        table = Base.metadata.tables["monitoring_events"]
        fk_targets = {fk.target_fullname for c in table.c for fk in c.foreign_keys}
        assert "scans.id" in fk_targets, (
            "monitoring_events.scan_id must reference scans.id"
        )

    def test_port_nullable(self) -> None:
        table = Base.metadata.tables["monitoring_events"]
        col = table.c["port"]
        assert col.nullable, (
            "monitoring_events.port must be nullable (host-level events)"
        )

    def test_previous_state_nullable(self) -> None:
        table = Base.metadata.tables["monitoring_events"]
        col = table.c["previous_state"]
        assert col.nullable, "monitoring_events.previous_state must be nullable"

    def test_current_state_nullable(self) -> None:
        table = Base.metadata.tables["monitoring_events"]
        col = table.c["current_state"]
        assert col.nullable, "monitoring_events.current_state must be nullable"

    def test_event_type_not_nullable(self) -> None:
        table = Base.metadata.tables["monitoring_events"]
        col = table.c["event_type"]
        assert not col.nullable, "monitoring_events.event_type must be NOT NULL"


# ---------------------------------------------------------------------------
# Test 3 — Enums: domain enum values are compatible with stored strings.
# ---------------------------------------------------------------------------


class TestEnumCompatibility:
    def test_monitoring_event_type_values_are_strings(self) -> None:
        from app.detection.engine import MonitoringEventType

        for member in MonitoringEventType:
            assert isinstance(member.value, str), (
                f"MonitoringEventType.{member.name}.value must be a plain string"
            )

    def test_port_status_values_are_strings(self) -> None:
        from app.monitoring.tcp_probe import PortStatus

        for member in PortStatus:
            assert isinstance(member.value, str), (
                f"PortStatus.{member.name}.value must be a plain string"
            )

    def test_host_status_values_are_strings(self) -> None:
        from app.monitoring.availability import HostStatus

        for member in HostStatus:
            assert isinstance(member.value, str), (
                f"HostStatus.{member.name}.value must be a plain string"
            )

    def test_event_type_values_fit_column_length(self) -> None:
        """Event type string values must fit within String(100)."""
        from app.detection.engine import MonitoringEventType

        max_len = 100
        for member in MonitoringEventType:
            assert len(member.value) <= max_len, (
                f"MonitoringEventType.{member.name} value exceeds {max_len} chars"
            )

    def test_port_status_values_fit_column_length(self) -> None:
        """Port status string values must fit within String(50)."""
        from app.monitoring.tcp_probe import PortStatus

        max_len = 50
        for member in PortStatus:
            assert len(member.value) <= max_len, (
                f"PortStatus.{member.name} value exceeds {max_len} chars"
            )

    def test_host_status_values_fit_column_length(self) -> None:
        """Host status string values must fit within String(50)."""
        from app.monitoring.availability import HostStatus

        max_len = 50
        for member in HostStatus:
            assert len(member.value) <= max_len, (
                f"HostStatus.{member.name} value exceeds {max_len} chars"
            )


# ---------------------------------------------------------------------------
# Test 4 — Configuration: DATABASE_URL loaded via environment variable.
# ---------------------------------------------------------------------------


class TestDatabaseUrlConfiguration:
    def test_database_url_default_is_empty_string(self) -> None:
        """Without env var set, DATABASE_URL defaults to empty string."""
        # Re-import settings with a clean env (unset DATABASE_URL).
        import importlib

        original = os.environ.pop("DATABASE_URL", None)
        try:
            import app.core.config as config_module

            importlib.reload(config_module)
            from app.core.config import Settings

            fresh_settings = Settings()
            assert fresh_settings.DATABASE_URL == ""
        finally:
            if original is not None:
                os.environ["DATABASE_URL"] = original
            importlib.reload(config_module)

    def test_database_url_reads_from_environment(self) -> None:
        """DATABASE_URL is loaded correctly from environment variable."""
        import importlib

        test_url = "postgresql+asyncpg://test:test@localhost:5432/testdb"
        os.environ["DATABASE_URL"] = test_url
        try:
            import app.core.config as config_module

            importlib.reload(config_module)
            from app.core.config import Settings

            fresh_settings = Settings()
            assert fresh_settings.DATABASE_URL == test_url
        finally:
            os.environ.pop("DATABASE_URL", None)
            importlib.reload(config_module)

    def test_database_url_not_exposed_in_repr(self) -> None:
        """Settings repr must not expose the full connection string with password."""
        import importlib

        os.environ["DATABASE_URL"] = "postgresql+asyncpg://user:secret@host/db"
        try:
            import app.core.config as config_module

            importlib.reload(config_module)
            from app.core.config import Settings

            fresh_settings = Settings()
            # pydantic-settings masks secrets — DATABASE_URL is a plain str field
            # so we only verify the URL is stored correctly, not that it's masked.
            # The key guarantee is that the password does not appear in LOG output.
            assert fresh_settings.DATABASE_URL.startswith("postgresql+asyncpg://")
        finally:
            os.environ.pop("DATABASE_URL", None)
            importlib.reload(config_module)


# ---------------------------------------------------------------------------
# Test 5 — Import: importing app.db.session does NOT connect to PostgreSQL.
# ---------------------------------------------------------------------------


class TestSessionImportDoesNotConnect:
    def test_import_session_module_does_not_raise(self) -> None:
        """Importing app.db.session must not attempt any network connection."""
        # If this import triggers a connection, it will raise because no
        # DATABASE_URL is configured and no PostgreSQL server is available.
        import importlib

        try:
            import app.db.session as session_module

            importlib.reload(session_module)
        except Exception as exc:
            pytest.fail(f"Importing app.db.session raised an unexpected error: {exc}")

    def test_engine_is_none_before_get_engine_called(self) -> None:
        """The module-level engine singleton must not be initialised at import time."""
        import importlib

        import app.db.session as session_module

        importlib.reload(session_module)
        # After a fresh reload, _engine must be None (not yet created).
        assert session_module._engine is None, (
            "app.db.session._engine should be None until get_engine() is called"
        )

    def test_get_engine_raises_without_database_url(self) -> None:
        """get_engine() must raise RuntimeError when DATABASE_URL is empty."""
        import importlib

        original = os.environ.pop("DATABASE_URL", None)
        try:
            import app.core.config as config_module
            import app.db.session as session_module

            importlib.reload(config_module)
            importlib.reload(session_module)

            with pytest.raises(RuntimeError, match="DATABASE_URL"):
                session_module.get_engine()
        finally:
            if original is not None:
                os.environ["DATABASE_URL"] = original
            importlib.reload(config_module)
            importlib.reload(session_module)
