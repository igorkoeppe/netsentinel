"""ORM model for PortResult — TCP probe outcome for a single port within a scan."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.scan import Scan


class PortResult(Base):
    """Persistent record of a single port probe within a scan.

    ``status`` stores the string value of ``PortStatus`` (e.g. "open",
    "closed", "timeout", "unreachable").

    ``response_time_ms`` may be None for probes that did not produce a
    measurable duration (e.g. unreachable hosts with no response).

    Only TCP is modelled at this stage. UDP support is out of scope for v0.3.
    """

    __tablename__ = "port_results"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scan_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("scans.id"), nullable=False, index=True
    )
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    response_time_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Relationship
    scan: Mapped[Scan] = relationship(
        "Scan",
        back_populates="port_results",
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<PortResult id={self.id} scan_id={self.scan_id} "
            f"port={self.port} status={self.status!r}>"
        )
