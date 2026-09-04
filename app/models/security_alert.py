"""ORM model for SecurityAlertRecord — a persisted security alert."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.host import Host
    from app.models.monitoring_event import MonitoringEventRecord
    from app.models.scan import Scan


class SecurityAlertRecord(Base):
    """Persistent record of a security alert generated from a monitoring event.

    ``alert_type`` and ``severity`` store the string values of ``AlertType``
    and ``Severity`` enums (e.g., "new_open_port", "high").

    ``port`` may be None for host-level alerts.
    """

    __tablename__ = "security_alerts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    host_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("hosts.id"), nullable=False, index=True
    )
    scan_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("scans.id"), nullable=True, index=True
    )
    monitoring_event_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("monitoring_events.id"), nullable=True
    )
    alert_type: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    # Relationships
    host: Mapped[Host] = relationship(
        "Host",
        back_populates="alerts",
        lazy="select",
    )
    scan: Mapped[Scan | None] = relationship(
        "Scan",
        back_populates="alerts",
        lazy="select",
    )
    monitoring_event: Mapped[MonitoringEventRecord | None] = relationship(
        "MonitoringEventRecord",
        back_populates="alert",
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<SecurityAlertRecord id={self.id} host_id={self.host_id} "
            f"alert_type={self.alert_type!r} severity={self.severity!r}>"
        )
