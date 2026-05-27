"""Round R G2 unified category and mart native mapping tables

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-26 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "unified_categories",
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("parent_id", sa.String(length=100), nullable=True),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name_ko", sa.String(length=100), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_origin", sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(["parent_id"], ["unified_categories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_unified_categories_parent", "unified_categories", ["parent_id"])
    op.create_index("ix_unified_categories_level_sort", "unified_categories", ["level", "sort_order"])

    op.create_table(
        "mart_category_mappings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("mart", sa.String(length=20), nullable=False),
        sa.Column("mart_native_id", sa.String(length=100), nullable=False),
        sa.Column("mart_native_path", sa.String(length=500), nullable=True),
        sa.Column("unified_category_id", sa.String(length=100), nullable=False),
        sa.Column("trust", sa.String(length=20), nullable=False, server_default="auto-aggregate"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("decided_by", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(["unified_category_id"], ["unified_categories.id"]),
        sa.UniqueConstraint("mart", "mart_native_id", name="uq_mart_category_mapping_native"),
        sa.CheckConstraint("mart IN ('emart', 'homeplus', 'lottemart', 'costco')", name="ck_mart_category_mapping_mart"),
        sa.CheckConstraint("trust IN ('human', 'external-ai', 'auto-aggregate')", name="ck_mart_category_mapping_trust"),
        sa.CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_mart_category_mapping_confidence"),
    )
    op.create_index("ix_mart_category_mappings_mart", "mart_category_mappings", ["mart"])
    op.create_index("ix_mart_category_mappings_unified", "mart_category_mappings", ["unified_category_id"])

    with op.batch_alter_table("products") as batch_op:
        batch_op.add_column(sa.Column("unified_category_id", sa.String(length=100), nullable=True))
        batch_op.create_foreign_key("fk_products_unified_category_id", "unified_categories", ["unified_category_id"], ["id"])
        batch_op.create_index("ix_products_unified_category_id", ["unified_category_id"])


def downgrade() -> None:
    with op.batch_alter_table("products") as batch_op:
        batch_op.drop_index("ix_products_unified_category_id")
        batch_op.drop_constraint("fk_products_unified_category_id", type_="foreignkey")
        batch_op.drop_column("unified_category_id")

    op.drop_index("ix_mart_category_mappings_unified", table_name="mart_category_mappings")
    op.drop_index("ix_mart_category_mappings_mart", table_name="mart_category_mappings")
    op.drop_table("mart_category_mappings")

    op.drop_index("ix_unified_categories_level_sort", table_name="unified_categories")
    op.drop_index("ix_unified_categories_parent", table_name="unified_categories")
    op.drop_table("unified_categories")
