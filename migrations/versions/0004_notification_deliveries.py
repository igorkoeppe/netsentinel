"""Add notification deliveries table

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-09 18:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("alert_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("notification_id", sa.String(length=64), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["alert_id"],
            ["security_alerts.id"],
            name="fk_notification_deliveries_alert_id",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_notification_deliveries_alert_id",
        "notification_deliveries",
        ["alert_id"],
    )
    op.create_index(
        "ix_notification_deliveries_channel",
        "notification_deliveries",
        ["channel"],
    )
    op.create_index(
        "ix_notification_deliveries_success",
        "notification_deliveries",
        ["success"],
    )
    op.create_index(
        "ix_notification_deliveries_created_at",
        "notification_deliveries",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_deliveries_created_at",
        table_name="notification_deliveries",
    )
    op.drop_index(
        "ix_notification_deliveries_success",
        table_name="notification_deliveries",
    )
    op.drop_index(
        "ix_notification_deliveries_channel",
        table_name="notification_deliveries",
    )
    op.drop_index(
        "ix_notification_deliveries_alert_id",
        table_name="notification_deliveries",
    )
    op.drop_table("notification_deliveries")
