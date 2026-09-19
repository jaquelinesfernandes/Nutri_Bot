"""add report period fields

Revision ID: b3c91f4e7d02
Revises: aa27ebf221d2
Create Date: 2026-06-18 00:00:00.000000

Adds:
- users.report_frequency (weekly|monthly|quarterly|none)
- weekly_reports.period_type (weekly|monthly|quarterly|custom)
- weekly_reports.period_end_date
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b3c91f4e7d02"
down_revision = "aa27ebf221d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("report_frequency", sa.String(20), nullable=False, server_default="weekly"),
    )
    op.add_column(
        "weekly_reports",
        sa.Column("period_type", sa.String(20), nullable=False, server_default="weekly"),
    )
    op.add_column(
        "weekly_reports",
        sa.Column("period_end_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("weekly_reports", "period_end_date")
    op.drop_column("weekly_reports", "period_type")
    op.drop_column("users", "report_frequency")
