"""ORM model for NotificationDeliveryRecord — notification delivery history."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.security_alert import SecurityAlertRecord


def _utcnow() -> datetime:
    return datetime.now(UTC)


class NotificationDeliveryRecord(Base):
    """Persistent audit record of an attempted notification delivery.

    Attributes:
        id: Primary key autoincrement.
        alert_id: Foreign key referencing security_alerts.id.
        channel: The delivery channel used (e.g., "webhook", "console").
        notification_id: Identifier of the dispatched notification.
        success: Whether delivery succeeded.
        delivered_at: Timestamp when delivery was confirmed, or None on failure.
        error_message: Error details if delivery failed, or None on success.
        created_at: Timestamp when this record was created.
        alert: Relationship back to the source SecurityAlertRecord.
    """

    __tablename__ = "notification_deliveries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    alert_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("security_alerts.id"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    notification_id: Mapped[str] = mapped_column(String(64), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
        index=True,
    )

    # Relationship back to security alert
    alert: Mapped[SecurityAlertRecord] = relationship(
        "SecurityAlertRecord",
        back_populates="deliveries",
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<NotificationDeliveryRecord id={self.id} alert_id={self.alert_id} "
            f"channel={self.channel!r} success={self.success}>"
        )
