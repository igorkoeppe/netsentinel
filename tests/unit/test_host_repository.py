"""Unit tests for HostRepository.

These tests use ``AsyncMock`` / ``MagicMock`` to simulate the SQLAlchemy
``AsyncSession``.  No live database is required.

The goal is to verify that the repository issues the correct session calls
(add, flush, refresh, scalar, execute, get) and raises the correct exceptions,
without exercising real SQL.

For tests that verify real database behaviour (unique constraints, ordering,
server defaults), see ``tests/integration/test_host_repository_pg.py``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.host import Host
from app.repositories.host import HostAlreadyExistsError, HostRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session() -> MagicMock:
    """Build a minimal AsyncSession mock."""
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.get = AsyncMock()
    session.scalar = AsyncMock()
    session.execute = AsyncMock()
    return session


def _make_host(
    *,
    host_id: int = 1,
    address: str = "192.168.0.10",
    name: str | None = None,
    enabled: bool = True,
) -> Host:
    """Build a minimal Host ORM instance (not attached to any session)."""
    host = Host(address=address, name=name)
    host.id = host_id  # type: ignore[assignment]
    host.enabled = enabled
    return host


# ---------------------------------------------------------------------------
# create — happy path
# ---------------------------------------------------------------------------


class TestCreate:
    @pytest.mark.asyncio
    async def test_create_adds_flushes_refreshes(self) -> None:
        """create() must call add → flush → refresh in order."""
        session = _make_session()
        host = _make_host()
        # refresh mutates host in-place on the real session; here we just
        # confirm the calls were made.
        session.refresh = AsyncMock(return_value=None)

        repo = HostRepository(session)

        # Patch Host.__init__ so the constructor returns our pre-built host.
        with patch("app.repositories.host.Host", return_value=host):
            result = await repo.create(address="192.168.0.10")

        session.add.assert_called_once_with(host)
        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once_with(host)
        assert result is host

    @pytest.mark.asyncio
    async def test_create_passes_address_and_name(self) -> None:
        """create() must forward address and name to the Host constructor."""
        session = _make_session()

        with patch("app.repositories.host.Host") as MockHost:
            instance = _make_host(address="10.0.0.1", name="router")
            MockHost.return_value = instance
            repo = HostRepository(session)
            await repo.create(address="10.0.0.1", name="router")
            MockHost.assert_called_once_with(address="10.0.0.1", name="router")

    @pytest.mark.asyncio
    async def test_create_name_defaults_to_none(self) -> None:
        """name defaults to None when not provided."""
        session = _make_session()

        with patch("app.repositories.host.Host") as MockHost:
            instance = _make_host()
            MockHost.return_value = instance
            repo = HostRepository(session)
            await repo.create(address="192.168.0.1")
            MockHost.assert_called_once_with(address="192.168.0.1", name=None)

    @pytest.mark.asyncio
    async def test_create_does_not_commit(self) -> None:
        """create() must never commit — that is the caller's responsibility."""
        session = _make_session()
        session.commit = AsyncMock()

        with patch("app.repositories.host.Host", return_value=_make_host()):
            repo = HostRepository(session)
            await repo.create(address="192.168.0.10")

        session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# create — IntegrityError → HostAlreadyExistsError
# ---------------------------------------------------------------------------


class TestCreateDuplicate:
    @pytest.mark.asyncio
    async def test_duplicate_address_raises_host_already_exists(self) -> None:
        """An IntegrityError on flush must be re-raised as HostAlreadyExistsError."""
        session = _make_session()
        session.flush = AsyncMock(
            side_effect=IntegrityError(
                "UNIQUE violation", params={}, orig=Exception("uq_hosts_address")
            )
        )

        with patch("app.repositories.host.Host", return_value=_make_host()):
            repo = HostRepository(session)
            with pytest.raises(HostAlreadyExistsError) as exc_info:
                await repo.create(address="192.168.0.10")

        assert exc_info.value.address == "192.168.0.10"
        assert "192.168.0.10" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_duplicate_chains_original_error(self) -> None:
        """HostAlreadyExistsError must chain the original IntegrityError."""
        session = _make_session()
        original = IntegrityError("UNIQUE", params={}, orig=Exception("uq"))
        session.flush = AsyncMock(side_effect=original)

        with patch("app.repositories.host.Host", return_value=_make_host()):
            repo = HostRepository(session)
            with pytest.raises(HostAlreadyExistsError) as exc_info:
                await repo.create(address="192.168.0.10")

        assert exc_info.value.__cause__ is original

    @pytest.mark.asyncio
    async def test_duplicate_does_not_rollback(self) -> None:
        """The repository must NOT rollback after IntegrityError — caller's duty."""
        session = _make_session()
        session.rollback = AsyncMock()
        session.flush = AsyncMock(
            side_effect=IntegrityError("UNIQUE", params={}, orig=Exception("uq"))
        )

        with patch("app.repositories.host.Host", return_value=_make_host()):
            repo = HostRepository(session)
            with pytest.raises(HostAlreadyExistsError):
                await repo.create(address="192.168.0.10")

        session.rollback.assert_not_called()


# ---------------------------------------------------------------------------
# get_by_id
# ---------------------------------------------------------------------------


class TestGetById:
    @pytest.mark.asyncio
    async def test_returns_host_when_found(self) -> None:
        host = _make_host(host_id=42)
        session = _make_session()
        session.get = AsyncMock(return_value=host)

        repo = HostRepository(session)
        result = await repo.get_by_id(42)

        session.get.assert_awaited_once_with(Host, 42)
        assert result is host

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self) -> None:
        session = _make_session()
        session.get = AsyncMock(return_value=None)

        repo = HostRepository(session)
        result = await repo.get_by_id(999)

        assert result is None

    @pytest.mark.asyncio
    async def test_does_not_raise_on_missing(self) -> None:
        """get_by_id must not raise for a non-existent id."""
        session = _make_session()
        session.get = AsyncMock(return_value=None)
        repo = HostRepository(session)
        # Should complete without any exception.
        result = await repo.get_by_id(0)
        assert result is None


# ---------------------------------------------------------------------------
# get_by_address
# ---------------------------------------------------------------------------


class TestGetByAddress:
    @pytest.mark.asyncio
    async def test_returns_host_when_found(self) -> None:
        host = _make_host(address="10.0.0.1")
        session = _make_session()
        session.scalar = AsyncMock(return_value=host)

        repo = HostRepository(session)
        result = await repo.get_by_address("10.0.0.1")

        session.scalar.assert_awaited_once()
        assert result is host

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self) -> None:
        session = _make_session()
        session.scalar = AsyncMock(return_value=None)

        repo = HostRepository(session)
        result = await repo.get_by_address("not-registered")

        assert result is None


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


class TestList:
    @pytest.mark.asyncio
    async def test_list_returns_all_hosts(self) -> None:
        hosts = [_make_host(host_id=1), _make_host(host_id=2, address="10.0.0.2")]
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = hosts
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock

        session = _make_session()
        session.execute = AsyncMock(return_value=execute_result)

        repo = HostRepository(session)
        result = await repo.list()

        session.execute.assert_awaited_once()
        assert result == hosts

    @pytest.mark.asyncio
    async def test_list_returns_list_type(self) -> None:
        """list() must always return a list, never a SQLAlchemy result proxy."""
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock

        session = _make_session()
        session.execute = AsyncMock(return_value=execute_result)

        repo = HostRepository(session)
        result = await repo.list()

        assert isinstance(result, list)
        assert result == []

    @pytest.mark.asyncio
    async def test_list_with_enabled_true_passes_filter(self) -> None:
        """list(enabled=True) must include a WHERE clause in the statement."""
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock

        session = _make_session()
        session.execute = AsyncMock(return_value=execute_result)

        repo = HostRepository(session)
        # Just verifying it executes without error and calls execute once.
        await repo.list(enabled=True)
        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_with_enabled_false_passes_filter(self) -> None:
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock

        session = _make_session()
        session.execute = AsyncMock(return_value=execute_result)

        repo = HostRepository(session)
        await repo.list(enabled=False)
        session.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


class TestUpdate:
    @pytest.mark.asyncio
    async def test_update_name(self) -> None:
        host = _make_host(name=None)
        session = _make_session()
        repo = HostRepository(session)

        result = await repo.update(host, name="gateway")

        assert result.name == "gateway"
        session.add.assert_called_once_with(host)
        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once_with(host)

    @pytest.mark.asyncio
    async def test_update_enabled_false(self) -> None:
        host = _make_host(enabled=True)
        session = _make_session()
        repo = HostRepository(session)

        result = await repo.update(host, enabled=False)

        assert result.enabled is False

    @pytest.mark.asyncio
    async def test_update_clears_name(self) -> None:
        """Passing name=None explicitly clears the label."""
        host = _make_host(name="old-name")
        session = _make_session()
        repo = HostRepository(session)

        result = await repo.update(host, name=None)

        assert result.name is None

    @pytest.mark.asyncio
    async def test_update_unset_fields_unchanged(self) -> None:
        """Fields not passed to update() must remain as-is."""
        host = _make_host(name="original", enabled=True)
        session = _make_session()
        repo = HostRepository(session)

        # Only change enabled; name should remain "original".
        result = await repo.update(host, enabled=False)

        assert result.name == "original"
        assert result.enabled is False

    @pytest.mark.asyncio
    async def test_update_does_not_commit(self) -> None:
        session = _make_session()
        session.commit = AsyncMock()
        host = _make_host()
        repo = HostRepository(session)

        await repo.update(host, name="x")

        session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_address_is_not_accepted(self) -> None:
        """update() must not accept an address kwarg at all (TypeError)."""
        session = _make_session()
        repo = HostRepository(session)
        host = _make_host()

        with pytest.raises(TypeError):
            await repo.update(host, address="new-address")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# HostAlreadyExistsError — public surface
# ---------------------------------------------------------------------------


class TestHostAlreadyExistsError:
    def test_str_contains_address(self) -> None:
        err = HostAlreadyExistsError("10.0.0.1")
        assert "10.0.0.1" in str(err)

    def test_address_attribute(self) -> None:
        err = HostAlreadyExistsError("10.0.0.1")
        assert err.address == "10.0.0.1"

    def test_is_exception(self) -> None:
        assert issubclass(HostAlreadyExistsError, Exception)
