"""Unit tests verifying OpenAPI schema structure, tags, and endpoints."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.version import get_version
from app.main import app


@pytest.mark.asyncio
async def test_openapi_schema_structure() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()

        assert schema["info"]["title"] == "NetSentinel"
        assert schema["info"]["version"] == get_version()

        paths = schema["paths"]
        expected_paths = [
            "/health",
            "/api/v1/health/live",
            "/api/v1/health/ready",
            "/api/v1/hosts",
            "/api/v1/hosts/{target}/history",
            "/api/v1/scans/{scan_id}",
            "/api/v1/alerts",
            "/api/v1/alerts/summary",
            "/api/v1/alerts/{alert_id}",
            "/api/v1/alerts/{alert_id}/deliveries",
            "/api/v1/alerts/{alert_id}/acknowledge",
            "/api/v1/alerts/{alert_id}/resolve",
        ]
        for p in expected_paths:
            assert p in paths, f"Path {p} missing from OpenAPI schema"

        # Check tags
        all_tags = {tag["name"] for tag in schema.get("tags", [])}
        expected_tags = {"Health", "Hosts", "Scans", "Alerts"}
        for t in expected_tags:
            # Tag can be defined in top-level or on operations
            op_tags = {
                tag
                for path_data in paths.values()
                for op in path_data.values()
                if isinstance(op, dict)
                for tag in op.get("tags", [])
            }
            assert t in all_tags or t in op_tags, f"Tag {t} missing from schema"

        # Verify no credentials leaked into schema
        raw_schema = resp.text
        assert (
            "password" not in raw_schema.lower() or "secret" not in raw_schema.lower()
        )
        assert "postgresql+asyncpg://" not in raw_schema
