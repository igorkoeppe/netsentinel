"""Add alert lifecycle columns (status, acknowledged_at, resolved_at)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-04 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "security_alerts",
        sa.Column(
            "status",
            sa.String(length=50),
            nullable=False,
            server_default="OPEN",
        ),
    )
    op.create_index("ix_security_alerts_status", "security_alerts", ["status"])
    op.add_column(
        "security_alerts",
        sa.Column(
            "acknowledged_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "security_alerts",
        sa.Column(
            "resolved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("security_alerts", "resolved_at")
    op.drop_column("security_alerts", "acknowledged_at")
    op.drop_index("ix_security_alerts_status", table_name="security_alerts")
    op.drop_column("security_alerts", "status")
