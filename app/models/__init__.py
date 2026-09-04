"""ORM models package.

Importing this package registers all models with ``Base.metadata``, which is
required for Alembic to auto-generate migrations correctly.

Do NOT import individual models directly from their modules in application
code — use this package instead to guarantee consistent metadata registration.
"""

from app.models.host import Host
from app.models.monitoring_event import MonitoringEventRecord
from app.models.port_result import PortResult
from app.models.scan import Scan
from app.models.security_alert import SecurityAlertRecord

__all__ = [
    "Host",
    "MonitoringEventRecord",
    "PortResult",
    "Scan",
    "SecurityAlertRecord",
]
