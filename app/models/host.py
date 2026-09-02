"""ORM model for Host — a monitored network target."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.monitoring_event import MonitoringEventRecord
    from app.models.scan import Scan


class Host(Base):
    """Persistent representation of a monitored network target.

    ``address`` carries a unique constraint because the same host endpoint
    must not be registered twice — it would produce duplicate monitoring
    sessions and ambiguous historical data.

    ``name`` is optional to allow quick registration with just an address.
    """

    __tablename__ = "hosts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        onupdate=func.now(),
    )

    # Relationships — lazy by default; no aggressive cascade configured at
    # this stage to prioritise safety and predictability.
    scans: Mapped[list[Scan]] = relationship(
        "Scan",
        back_populates="host",
        lazy="select",
    )
    events: Mapped[list[MonitoringEventRecord]] = relationship(
        "MonitoringEventRecord",
        back_populates="host",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Host id={self.id} address={self.address!r} enabled={self.enabled}>"
