"""Repositories package — data access layer.

Each repository encapsulates all database operations for a single ORM model.
Application code (services, API handlers) must not write SQLAlchemy queries
directly; it should call repository methods instead.

Usage::

    from app.repositories import HostRepository, HostAlreadyExistsError
    from app.repositories import ScanRepository, ScanHostNotFoundError, PortResultInput
    from app.repositories import MonitoringEventRepository
    from app.repositories import AlertRepository
"""

from app.repositories.alert import AlertRepository
from app.repositories.host import HostAlreadyExistsError, HostRepository
from app.repositories.monitoring_event import MonitoringEventRepository
from app.repositories.scan import PortResultInput, ScanHostNotFoundError, ScanRepository

__all__ = [
    "AlertRepository",
    "HostRepository",
    "HostAlreadyExistsError",
    "ScanRepository",
    "ScanHostNotFoundError",
    "PortResultInput",
    "MonitoringEventRepository",
]
