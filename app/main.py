"""NetSentinel FastAPI application entrypoint."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_error_handlers
from app.api.routes import (
    alerts_router,
    health_router,
    hosts_router,
    scans_router,
)
from app.core.config import settings
from app.core.version import get_version
from app.db.session import dispose_engine


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager.

    Database connections are created lazily on first access.
    On application shutdown, active pools are gracefully released.
    """
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    app = FastAPI(
        title=settings.APP_NAME,
        version=get_version(),
        description="Network monitoring and security observability platform.",
        lifespan=lifespan,
    )

    # Opt-in CORS configuration
    cors_origins = settings.get_cors_origins()
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "X-API-Key"],
        )

    # Register standardized error and validation handlers
    register_error_handlers(app)

    # Legacy health endpoint preserved for backwards compatibility
    @app.get("/health", tags=["Health"], include_in_schema=True)
    async def legacy_health() -> dict[str, str]:
        return {"status": "ok", "service": settings.APP_NAME.lower()}

    # Versioned REST API routes under /api/v1
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(health_router)
    api_v1.include_router(hosts_router)
    api_v1.include_router(scans_router)
    api_v1.include_router(alerts_router)

    app.include_router(api_v1)

    return app


app = create_app()
