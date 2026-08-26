"""Persist authenticated hotdeal reports.

Revision ID: rpt1_hotdeal_reports
Revises: w5c_catalog_sync_log
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "rpt1_hotdeal_reports"
down_revision: Union[str, Sequence[str], None] = "w5c_catalog_sync_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "hotdeal_reports" in inspector.get_table_names():
        return

    op.create_table(
        "hotdeal_reports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("hotdeal_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["hotdeal_id"], ["hotdeal_prices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hotdeal_id", "user_id", name="uq_hotdeal_report_hotdeal_user"),
    )
    op.create_index("ix_hotdeal_reports_hotdeal", "hotdeal_reports", ["hotdeal_id"], unique=False)
    op.create_index("ix_hotdeal_reports_status", "hotdeal_reports", ["status", "created_at"], unique=False)
    op.create_index("ix_hotdeal_reports_user", "hotdeal_reports", ["user_id", "created_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "hotdeal_reports" not in inspector.get_table_names():
        return
    op.drop_index("ix_hotdeal_reports_user", table_name="hotdeal_reports")
    op.drop_index("ix_hotdeal_reports_status", table_name="hotdeal_reports")
    op.drop_index("ix_hotdeal_reports_hotdeal", table_name="hotdeal_reports")
    op.drop_table("hotdeal_reports")
