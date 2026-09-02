"""ORM model for Scan — a single monitoring execution recorded in the database."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.host import Host
    from app.models.monitoring_event import MonitoringEventRecord
    from app.models.port_result import PortResult


class Scan(Base):
    """Persistent record of a single host scan (one monitoring cycle).

    ``status`` stores the string value of ``HostStatus`` (e.g. "available",
    "unavailable") — plain strings decouple the ORM from the domain enum,
    which keeps migrations simpler and avoids enum-type lock-in.

    ``response_time_ms`` may be None for scans that did not complete
    (e.g. immediately cancelled or errored before the first probe result).
    """

    __tablename__ = "scans"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    host_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("hosts.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    response_time_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    host: Mapped[Host] = relationship(
        "Host",
        back_populates="scans",
        lazy="select",
    )
    port_results: Mapped[list[PortResult]] = relationship(
        "PortResult",
        back_populates="scan",
        lazy="select",
    )
    events: Mapped[list[MonitoringEventRecord]] = relationship(
        "MonitoringEventRecord",
        back_populates="scan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<Scan id={self.id} host_id={self.host_id} "
            f"status={self.status!r} started_at={self.started_at}>"
        )
