"""Shared fixtures for the unit test suite.

Unit tests must never need a live database. FastAPI resolves dependencies such
as ``get_session`` before it validates query and path parameters, so even a
request that is rejected with 422 or 404 opens a session first. Without
``DATABASE_URL`` that raises, and the test fails for a reason unrelated to the
behaviour under test.

The autouse fixture below replaces ``get_session`` with a guard object. Tests
that need a session still install their own override (which takes precedence);
any test that ends up touching the guard fails loudly instead of silently
reaching for a real database.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.api.dependencies import get_session
from app.main import app


class _NoDatabaseSession:
    """Stand-in session that fails on any use."""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(
            f"Unit test used the database session (attribute {name!r}). "
            "Override get_session with a mock or move the test to "
            "tests/integration."
        )


def _no_database_session() -> _NoDatabaseSession:
    return _NoDatabaseSession()


@pytest.fixture(autouse=True)
def _isolate_api_from_database() -> Iterator[None]:
    app.dependency_overrides[get_session] = _no_database_session
    try:
        yield
    finally:
        if app.dependency_overrides.get(get_session) is _no_database_session:
            del app.dependency_overrides[get_session]
