"""API routes package."""

from app.api.routes.alerts import router as alerts_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.health import router as health_router
from app.api.routes.hosts import router as hosts_router
from app.api.routes.scans import router as scans_router

__all__ = [
    "alerts_router",
    "dashboard_router",
    "health_router",
    "hosts_router",
    "scans_router",
]
