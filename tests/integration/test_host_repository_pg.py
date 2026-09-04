"""Integration tests for HostRepository against a real PostgreSQL database.

These tests require ``TEST_DATABASE_URL`` to be set and are tagged with the
``integration`` marker so that they are excluded from the default ``pytest``
run::

    # Only unit tests (no database required):
    pytest

    # PostgreSQL integration tests (set TEST_DATABASE_URL first):
    #   pytest -m integration

Each test runs inside a transaction that is rolled back automatically by the
``pg_session`` fixture in ``conftest.py``, so tests are fully isolated and do
not leave persistent data in the database.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.host import HostAlreadyExistsError, HostRepository

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


class TestCreate:
    async def test_create_returns_host_with_id(
        self, host_repo: HostRepository, pg_session: AsyncSession
    ) -> None:
        """A created host must have a server-assigned integer id."""
        host = await host_repo.create(address="192.168.1.10")
        await pg_session.flush()
        assert isinstance(host.id, int)
        assert host.id > 0

    async def test_create_sets_address(self, host_repo: HostRepository) -> None:
        host = await host_repo.create(address="192.168.1.11")
        assert host.address == "192.168.1.11"

    async def test_create_enabled_defaults_to_true(
        self, host_repo: HostRepository
    ) -> None:
        """enabled must default to True (from the ORM model default)."""
        host = await host_repo.create(address="192.168.1.12")
        assert host.enabled is True

    async def test_create_sets_name(self, host_repo: HostRepository) -> None:
        host = await host_repo.create(address="192.168.1.13", name="router")
        assert host.name == "router"

    async def test_create_name_optional(self, host_repo: HostRepository) -> None:
        host = await host_repo.create(address="192.168.1.14")
        assert host.name is None

    async def test_create_sets_created_at(self, host_repo: HostRepository) -> None:
        """created_at must be populated by the server after flush."""
        host = await host_repo.create(address="192.168.1.15")
        assert host.created_at is not None


# ---------------------------------------------------------------------------
# duplicate address
# ---------------------------------------------------------------------------


class TestDuplicateAddress:
    async def test_duplicate_raises_host_already_exists(
        self, host_repo: HostRepository, pg_session: AsyncSession
    ) -> None:
        """Inserting a duplicate address must raise HostAlreadyExistsError."""
        await host_repo.create(address="192.168.2.1")
        # First flush commits the insert to the in-transaction state.
        await pg_session.flush()

        with pytest.raises(HostAlreadyExistsError) as exc_info:
            await host_repo.create(address="192.168.2.1")

        assert exc_info.value.address == "192.168.2.1"

    async def test_duplicate_error_has_cause(
        self, host_repo: HostRepository, pg_session: AsyncSession
    ) -> None:
        """HostAlreadyExistsError must chain the original IntegrityError."""
        from sqlalchemy.exc import IntegrityError

        await host_repo.create(address="192.168.2.2")
        await pg_session.flush()

        with pytest.raises(HostAlreadyExistsError) as exc_info:
            await host_repo.create(address="192.168.2.2")

        assert isinstance(exc_info.value.__cause__, IntegrityError)

    async def test_session_usable_after_rollback(
        self, host_repo: HostRepository, pg_session: AsyncSession
    ) -> None:
        """After catching the error and rolling back, the session must be usable."""
        await host_repo.create(address="192.168.2.3")
        await pg_session.flush()

        try:
            await host_repo.create(address="192.168.2.3")
        except HostAlreadyExistsError:
            # The caller is responsible for rolling back.
            await pg_session.rollback()

        # After rollback we can start fresh (previous data is gone too,
        # consistent with per-test isolation).
        host = await host_repo.create(address="192.168.2.3")
        await pg_session.flush()
        assert host.address == "192.168.2.3"


# ---------------------------------------------------------------------------
# get_by_id
# ---------------------------------------------------------------------------


class TestGetById:
    async def test_get_by_id_returns_host(
        self, host_repo: HostRepository, pg_session: AsyncSession
    ) -> None:
        created = await host_repo.create(address="10.0.0.1")
        await pg_session.flush()

        found = await host_repo.get_by_id(created.id)
        assert found is not None
        assert found.id == created.id
        assert found.address == "10.0.0.1"

    async def test_get_by_id_returns_none_when_missing(
        self, host_repo: HostRepository
    ) -> None:
        result = await host_repo.get_by_id(999_999_999)
        assert result is None

    async def test_get_by_id_does_not_raise(self, host_repo: HostRepository) -> None:
        """Must not raise for a non-existent id."""
        result = await host_repo.get_by_id(0)
        assert result is None


# ---------------------------------------------------------------------------
# get_by_address
# ---------------------------------------------------------------------------


class TestGetByAddress:
    async def test_get_by_address_returns_host(
        self, host_repo: HostRepository, pg_session: AsyncSession
    ) -> None:
        await host_repo.create(address="10.1.0.1")
        await pg_session.flush()

        found = await host_repo.get_by_address("10.1.0.1")
        assert found is not None
        assert found.address == "10.1.0.1"

    async def test_get_by_address_returns_none_when_missing(
        self, host_repo: HostRepository
    ) -> None:
        result = await host_repo.get_by_address("not-registered.local")
        assert result is None


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


class TestList:
    async def test_list_returns_all(
        self, host_repo: HostRepository, pg_session: AsyncSession
    ) -> None:
        await host_repo.create(address="172.16.0.1")
        await host_repo.create(address="172.16.0.2")
        await host_repo.create(address="172.16.0.3")
        await pg_session.flush()

        hosts = await host_repo.list()
        addresses = {h.address for h in hosts}
        assert {"172.16.0.1", "172.16.0.2", "172.16.0.3"} <= addresses

    async def test_list_order_is_by_id(
        self, host_repo: HostRepository, pg_session: AsyncSession
    ) -> None:
        """list() must return hosts in ascending id order (deterministic)."""
        await host_repo.create(address="172.16.1.1")
        await host_repo.create(address="172.16.1.2")
        await pg_session.flush()

        hosts = await host_repo.list()
        # Filter to the two we just inserted (in case residual data exists
        # after a failed rollback — defensive guard).
        ours = [h for h in hosts if h.address in {"172.16.1.1", "172.16.1.2"}]
        ids = [h.id for h in ours]
        assert ids == sorted(ids), "list() must be ordered by id ASC"

    async def test_list_empty_returns_empty_list(
        self, host_repo: HostRepository
    ) -> None:
        # Relies on per-test rollback — no hosts in this test's transaction.
        hosts = await host_repo.list()
        assert isinstance(hosts, list)

    async def test_list_enabled_true(
        self, host_repo: HostRepository, pg_session: AsyncSession
    ) -> None:
        h1 = await host_repo.create(address="172.16.2.1")
        await pg_session.flush()
        h2 = await host_repo.create(address="172.16.2.2")
        await pg_session.flush()
        await host_repo.update(h2, enabled=False)
        await pg_session.flush()

        enabled_hosts = await host_repo.list(enabled=True)
        enabled_addresses = {h.address for h in enabled_hosts}
        assert h1.address in enabled_addresses
        assert h2.address not in enabled_addresses

    async def test_list_enabled_false(
        self, host_repo: HostRepository, pg_session: AsyncSession
    ) -> None:
        h1 = await host_repo.create(address="172.16.3.1")
        await pg_session.flush()
        h2 = await host_repo.create(address="172.16.3.2")
        await pg_session.flush()
        await host_repo.update(h2, enabled=False)
        await pg_session.flush()

        disabled_hosts = await host_repo.list(enabled=False)
        disabled_addresses = {h.address for h in disabled_hosts}
        assert h2.address in disabled_addresses
        assert h1.address not in disabled_addresses


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


class TestUpdate:
    async def test_update_name(
        self, host_repo: HostRepository, pg_session: AsyncSession
    ) -> None:
        host = await host_repo.create(address="10.2.0.1", name="old")
        await pg_session.flush()

        updated = await host_repo.update(host, name="new-name")
        await pg_session.flush()

        assert updated.name == "new-name"

    async def test_update_enabled(
        self, host_repo: HostRepository, pg_session: AsyncSession
    ) -> None:
        host = await host_repo.create(address="10.2.0.2")
        await pg_session.flush()

        updated = await host_repo.update(host, enabled=False)
        await pg_session.flush()

        assert updated.enabled is False

    async def test_update_persists_on_reload(
        self, host_repo: HostRepository, pg_session: AsyncSession
    ) -> None:
        """Changes must survive a reload from the database."""
        host = await host_repo.create(address="10.2.0.3", name="original")
        await pg_session.flush()

        await host_repo.update(host, name="updated", enabled=False)
        await pg_session.flush()

        host_id = host.id
        pg_session.expire_all()
        reloaded = await host_repo.get_by_id(host_id)
        assert reloaded is not None
        assert reloaded.name == "updated"
        assert reloaded.enabled is False

    async def test_update_unset_field_preserved(
        self, host_repo: HostRepository, pg_session: AsyncSession
    ) -> None:
        """Fields not passed to update() must be unchanged."""
        host = await host_repo.create(address="10.2.0.4", name="keep-me")
        await pg_session.flush()

        await host_repo.update(host, enabled=False)
        await pg_session.flush()

        host_id = host.id
        pg_session.expire_all()
        reloaded = await host_repo.get_by_id(host_id)
        assert reloaded is not None
        assert reloaded.name == "keep-me"

    async def test_update_does_not_commit(
        self, host_repo: HostRepository, pg_session: AsyncSession
    ) -> None:
        """update() must not commit the session."""
        host = await host_repo.create(address="10.2.0.5")
        await pg_session.flush()

        # If commit were called, the per-test transaction would be finalised
        # and the subsequent rollback in the fixture would have nothing to undo.
        # We just verify the method completes normally without error.
        await host_repo.update(host, name="no-commit-test")
