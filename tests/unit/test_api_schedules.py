"""Unit tests for /api/v1/schedules endpoints (service layer mocked)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_session
from app.core.config import Settings
from app.main import app
from app.services.scan_schedule import (
    InvalidScheduleError,
    ScheduleAlreadyExistsError,
    ScheduleItem,
    ScheduleNotFoundError,
)

_NOW = datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC)
_KEY = "schedule-secret"
_SERVICE = "app.services.scan_schedule.ScanScheduleService"


def _item(**overrides: object) -> ScheduleItem:
    values: dict[str, object] = {
        "id": 3,
        "host_id": 7,
        "address": "192.168.1.10",
        "name": "nas",
        "ports": (22, 443),
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


@pytest.fixture(autouse=True)
def _session_override() -> Iterator[None]:
    app.dependency_overrides[get_session] = lambda: AsyncMock()
    try:
        yield
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_list_schedules(client: AsyncClient) -> None:
    with (
        patch.object(Settings, "get_api_key", return_value=None),
        patch(
            f"{_SERVICE}.list_schedules",
            new_callable=AsyncMock,
            return_value=[_item(last_error="TimeoutError: boom")],
        ) as mock_list,
    ):
        resp = await client.get("/api/v1/schedules?limit=5&enabled=true")

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1 and data["limit"] == 5
    item = data["items"][0]
    assert item["target"] == "192.168.1.10"
    assert item["ports"] == [22, 443]
    assert item["interval_seconds"] == 300
    assert item["last_error"] == "TimeoutError: boom"
    assert item["next_run_at"].startswith("2026-10-22T12:00:00")
    mock_list.assert_awaited_once_with(limit=5, offset=0, enabled=True)


async def test_get_schedule_not_found(client: AsyncClient) -> None:
    with (
        patch.object(Settings, "get_api_key", return_value=None),
        patch(
            f"{_SERVICE}.get_schedule",
            new_callable=AsyncMock,
            side_effect=ScheduleNotFoundError(9),
        ),
    ):
        resp = await client.get("/api/v1/schedules/9")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "SCHEDULE_NOT_FOUND"


async def test_create_is_disabled_without_api_key(client: AsyncClient) -> None:
    with patch.object(Settings, "get_api_key", return_value=None):
        resp = await client.post(
            "/api/v1/schedules", json={"target": "127.0.0.1", "ports": [22]}
        )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "MUTATIONS_DISABLED"


async def test_create_requires_valid_key(client: AsyncClient) -> None:
    with patch.object(Settings, "get_api_key", return_value=_KEY):
        resp = await client.post(
            "/api/v1/schedules",
            json={"target": "127.0.0.1", "ports": [22]},
            headers={"X-API-Key": "wrong"},
        )
    assert resp.status_code == 401


async def test_create_schedule(client: AsyncClient) -> None:
    with (
        patch.object(Settings, "get_api_key", return_value=_KEY),
        patch(
            f"{_SERVICE}.create_schedule",
            new_callable=AsyncMock,
            return_value=_item(),
        ) as mock_create,
    ):
        resp = await client.post(
            "/api/v1/schedules",
            json={
                "target": "192.168.1.10",
                "ports": [443, 22],
                "interval_seconds": 300,
            },
            headers={"X-API-Key": _KEY},
        )

    assert resp.status_code == 201
    assert resp.json()["id"] == 3
    kwargs = mock_create.await_args.kwargs
    assert kwargs["target"] == "192.168.1.10"
    assert kwargs["ports"] == [443, 22]
    assert kwargs["interval_seconds"] == 300
    assert kwargs["enabled"] is True


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (ScheduleAlreadyExistsError(7), 409, "SCHEDULE_EXISTS"),
        (InvalidScheduleError("Interval must be at least 60"), 422, "VALIDATION_ERROR"),
    ],
)
async def test_create_schedule_errors(
    client: AsyncClient, error: Exception, status: int, code: str
) -> None:
    with (
        patch.object(Settings, "get_api_key", return_value=_KEY),
        patch(f"{_SERVICE}.create_schedule", new_callable=AsyncMock, side_effect=error),
    ):
        resp = await client.post(
            "/api/v1/schedules",
            json={"target": "192.168.1.10", "ports": [22]},
            headers={"X-API-Key": _KEY},
        )
    assert resp.status_code == status
    assert resp.json()["error"]["code"] == code


@pytest.mark.parametrize(
    "body",
    [
        {"target": "127.0.0.1", "ports": []},
        {"target": "127.0.0.1", "ports": list(range(1, 102))},
        {"target": "127.0.0.1", "ports": [22], "interval_seconds": 0},
        {"target": "127.0.0.1", "ports": [22], "unexpected": True},
    ],
)
async def test_create_schedule_body_validation(
    client: AsyncClient, body: dict[str, object]
) -> None:
    with patch.object(Settings, "get_api_key", return_value=_KEY):
        resp = await client.post(
            "/api/v1/schedules", json=body, headers={"X-API-Key": _KEY}
        )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_update_schedule(client: AsyncClient) -> None:
    with (
        patch.object(Settings, "get_api_key", return_value=_KEY),
        patch(
            f"{_SERVICE}.update_schedule",
            new_callable=AsyncMock,
            return_value=_item(enabled=False),
        ) as mock_update,
    ):
        resp = await client.patch(
            "/api/v1/schedules/3", json={"enabled": False}, headers={"X-API-Key": _KEY}
        )

    assert resp.status_code == 200
    assert resp.json()["enabled"] is False
    args = mock_update.await_args
    assert args.args == (3,)
    assert args.kwargs["enabled"] is False
    assert args.kwargs["ports"] is None
    assert args.kwargs["interval_seconds"] is None


async def test_update_unknown_schedule(client: AsyncClient) -> None:
    with (
        patch.object(Settings, "get_api_key", return_value=_KEY),
        patch(
            f"{_SERVICE}.update_schedule",
            new_callable=AsyncMock,
            side_effect=ScheduleNotFoundError(3),
        ),
    ):
        resp = await client.patch(
            "/api/v1/schedules/3", json={"enabled": True}, headers={"X-API-Key": _KEY}
        )
    assert resp.status_code == 404
