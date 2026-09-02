"""Initial schema — v0.3.0

Creates the four core tables for NetSentinel persistence:
- hosts
- scans
- port_results
- monitoring_events

Revision ID: 0001
Revises: (none — initial migration)
Create Date: 2026-08-28 UTC

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create all tables in dependency order (parents before children)."""

    # 1. hosts — no foreign key dependencies.
    op.create_table(
        "hosts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("address", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("address", name="uq_hosts_address"),
    )

    # 2. scans — foreign key to hosts.
    op.create_table(
        "scans",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("host_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("response_time_ms", sa.Float(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["host_id"], ["hosts.id"], name="fk_scans_host_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scans_host_id", "scans", ["host_id"])

    # 3. port_results — foreign key to scans.
    op.create_table(
        "port_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("scan_id", sa.Integer(), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("response_time_ms", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["scan_id"], ["scans.id"], name="fk_port_results_scan_id"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_port_results_scan_id", "port_results", ["scan_id"])

    # 4. monitoring_events — foreign keys to hosts and scans.
    op.create_table(
        "monitoring_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("host_id", sa.Integer(), nullable=False),
        sa.Column("scan_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("previous_state", sa.String(length=100), nullable=True),
        sa.Column("current_state", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["host_id"], ["hosts.id"], name="fk_monitoring_events_host_id"
        ),
        sa.ForeignKeyConstraint(
            ["scan_id"], ["scans.id"], name="fk_monitoring_events_scan_id"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_monitoring_events_host_id", "monitoring_events", ["host_id"])
    op.create_index("ix_monitoring_events_scan_id", "monitoring_events", ["scan_id"])


def downgrade() -> None:
    """Drop all tables in reverse dependency order (children before parents)."""

    op.drop_index("ix_monitoring_events_scan_id", table_name="monitoring_events")
    op.drop_index("ix_monitoring_events_host_id", table_name="monitoring_events")
    op.drop_table("monitoring_events")

    op.drop_index("ix_port_results_scan_id", table_name="port_results")
    op.drop_table("port_results")

    op.drop_index("ix_scans_host_id", table_name="scans")
    op.drop_table("scans")

    op.drop_table("hosts")
