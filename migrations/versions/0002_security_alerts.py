"""Add security alerts table

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-03 19:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "security_alerts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("host_id", sa.Integer(), nullable=False),
        sa.Column("scan_id", sa.Integer(), nullable=True),
        sa.Column("monitoring_event_id", sa.Integer(), nullable=True),
        sa.Column("alert_type", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=50), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["host_id"], ["hosts.id"], name="fk_security_alerts_host_id"
        ),
        sa.ForeignKeyConstraint(
            ["scan_id"], ["scans.id"], name="fk_security_alerts_scan_id"
        ),
        sa.ForeignKeyConstraint(
            ["monitoring_event_id"],
            ["monitoring_events.id"],
            name="fk_security_alerts_monitoring_event_id",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_security_alerts_host_id", "security_alerts", ["host_id"])
    op.create_index("ix_security_alerts_scan_id", "security_alerts", ["scan_id"])
    op.create_index("ix_security_alerts_severity", "security_alerts", ["severity"])
    op.create_index("ix_security_alerts_created_at", "security_alerts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_security_alerts_created_at", table_name="security_alerts")
    op.drop_index("ix_security_alerts_severity", table_name="security_alerts")
    op.drop_index("ix_security_alerts_scan_id", table_name="security_alerts")
    op.drop_index("ix_security_alerts_host_id", table_name="security_alerts")
    op.drop_table("security_alerts")
