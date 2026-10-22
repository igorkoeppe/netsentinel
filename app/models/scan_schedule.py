"""ORM model for ScanSchedule — a periodic scan configured for a host."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.host import Host


class ScanSchedule(Base):
    """Persistent configuration of a periodic scan for one host.

    ``host_id`` is unique: each target has at most one schedule, so the
    "previous scan" used as the detection baseline is never ambiguous.

    ``ports`` is an explicit list of TCP ports (no ranges are expanded here).
    ``next_run_at`` drives the scheduler: a schedule is due when it is enabled
    and ``next_run_at <= now``. The ``last_*`` columns record the outcome of
    the most recent run for operators; the full history lives in ``scans``.

    Schedules are never deleted by the application (the runtime database role
    has no DELETE privilege); they are disabled instead.
    """

    __tablename__ = "scan_schedules"
    __table_args__ = (
        CheckConstraint("interval_seconds > 0", name="ck_scan_schedules_interval"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    host_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("hosts.id"), nullable=False, unique=True
    )
    ports: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_scan_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("scans.id"), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
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

    host: Mapped[Host] = relationship("Host", lazy="select")

    def __repr__(self) -> str:
        return (
            f"<ScanSchedule id={self.id} host_id={self.host_id} "
            f"interval={self.interval_seconds}s enabled={self.enabled}>"
        )
