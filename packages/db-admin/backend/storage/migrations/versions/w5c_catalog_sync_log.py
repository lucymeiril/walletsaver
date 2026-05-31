"""Catalog Sync: catalog_sync_log audit table

Revision ID: w5c_catalog_sync_log
Revises: v4m_product_match_rules
Create Date: 2026-05-27 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "w5c_catalog_sync_log"
down_revision: Union[str, Sequence[str], None] = "v4m_product_match_rules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "catalog_sync_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("operation", sa.String(length=30), nullable=False),
        sa.Column("entities", sa.JSON(), nullable=True),
        sa.Column("mode", sa.String(length=20), nullable=True),
        sa.Column("scope", sa.JSON(), nullable=True),
        sa.Column("counts", sa.JSON(), nullable=True),
        sa.Column("file_hash", sa.String(length=64), nullable=True),
        sa.Column("snapshot_path", sa.String(length=500), nullable=True),
        sa.Column("user", sa.String(length=255), nullable=False, server_default="anonymous"),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("force", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_catalog_sync_log_operation", "catalog_sync_log", ["operation"], unique=False)
    op.create_index("ix_catalog_sync_log_timestamp", "catalog_sync_log", ["timestamp"], unique=False)
    op.create_index("ix_catalog_sync_log_file_hash", "catalog_sync_log", ["file_hash"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_catalog_sync_log_file_hash", table_name="catalog_sync_log")
    op.drop_index("ix_catalog_sync_log_timestamp", table_name="catalog_sync_log")
    op.drop_index("ix_catalog_sync_log_operation", table_name="catalog_sync_log")
    op.drop_table("catalog_sync_log")
