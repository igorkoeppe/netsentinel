"""Health, liveness, and database readiness endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.core.config import settings
from app.core.version import get_version
from app.db.session import get_engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])


@router.get(
    "/health/live",
    summary="Liveness probe",
    description="Confirms that the service is running. Never connects to PostgreSQL.",
    response_model=dict[str, str],
)
async def liveness() -> dict[str, str]:
    """Check service liveness without accessing any persistence layer."""
    return {
        "status": "ok",
        "service": settings.APP_NAME,
        "version": get_version(),
    }


@router.get(
    "/health/ready",
    summary="Readiness probe",
    description=(
        "Verifies that required persistent components (PostgreSQL) are accessible."
    ),
    response_model=dict[str, str],
)
async def readiness(response: Response) -> dict[str, str]:
    """Check database connectivity. Returns HTTP 503 if unavailable or unconfigured."""
    if not settings.DATABASE_URL:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable", "database": "not_configured"}

    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ready", "database": "available"}
    except Exception as exc:
        # Sanitized error response — never log or expose credentials or raw exceptions
        logger.warning("Readiness probe check failed: %s", type(exc).__name__)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable", "database": "unavailable"}
