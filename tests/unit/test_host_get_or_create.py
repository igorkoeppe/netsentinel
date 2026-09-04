"""The losing insert must reuse the winner without breaking the transaction."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.models.host import Host
from app.repositories.host import HostRepository


@pytest.mark.parametrize("outcome", ["existing", "inserted", "conflict"])
async def test_get_or_create_resolves_one_host(outcome):
    host = Host(id=7, address="127.0.0.1", name="preserved", enabled=False)
    session = MagicMock()
    responses = {
        "existing": [host],
        "inserted": [None, host],
        "conflict": [None, None, host],
    }
    session.scalar = AsyncMock(side_effect=responses[outcome])
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    assert await HostRepository(session).get_or_create(address=host.address) is host
    assert host.name == "preserved"
    assert host.enabled is False
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()
    assert session.scalar.await_count == len(responses[outcome])
    if outcome != "existing":
        stmt = session.scalar.await_args_list[1].args[0]
        compiled = stmt.compile(dialect=postgresql.dialect())
        assert "ON CONFLICT (address) DO NOTHING RETURNING" in str(compiled)
        assert compiled.params["address"] == host.address


async def test_get_or_create_does_not_hide_other_integrity_errors():
    session = MagicMock()
    error = IntegrityError("test", {}, ValueError("different constraint"))
    session.scalar = AsyncMock(side_effect=[None, error])
    with pytest.raises(IntegrityError):
        await HostRepository(session).get_or_create(address="127.0.0.1")


async def test_deleted_conflict_does_not_return_invalid_host():
    session = MagicMock()
    session.scalar = AsyncMock(side_effect=[None, None, None])
    with pytest.raises(RuntimeError, match="disappeared"):
        await HostRepository(session).get_or_create(address="127.0.0.1")
