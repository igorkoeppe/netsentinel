"""ORM model for MonitoringEventRecord — a persisted network state change event.

The class is named ``MonitoringEventRecord`` (not ``MonitoringEvent``) to avoid
shadowing the in-memory domain dataclass ``MonitoringEvent`` defined in
``app.detection.engine``.  Both coexist without conflict:

- ``MonitoringEvent``       — pure in-memory dataclass, no ORM dependency.
- ``MonitoringEventRecord`` — ORM model persisted to ``monitoring_events``.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.host import Host
    from app.models.scan import Scan


class MonitoringEventRecord(Base):
    """Persistent record of a network state change detected by the engine.

    ``event_type`` stores the string value of ``MonitoringEventType``
    (e.g. "port_opened", "host_became_unavailable").

    ``scan_id`` is nullable because future event types may not be tied
    to a specific scan (e.g. configuration-level changes).

    ``port``, ``previous_state`` and ``current_state`` are nullable because
    host-level events (HOST_BECAME_UNAVAILABLE) do not relate to a specific port.
    """

    __tablename__ = "monitoring_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    host_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("hosts.id"), nullable=False, index=True
    )
    scan_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("scans.id"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    previous_state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    current_state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    host: Mapped[Host] = relationship(
        "Host",
        back_populates="events",
        lazy="select",
    )
    scan: Mapped[Scan | None] = relationship(
        "Scan",
        back_populates="events",
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<MonitoringEventRecord id={self.id} host_id={self.host_id} "
            f"event_type={self.event_type!r} port={self.port}>"
        )
