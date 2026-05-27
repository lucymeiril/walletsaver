"""Round V: product title match rules

Revision ID: v4m_product_match_rules
Revises: 5d59c7faa3b9
Create Date: 2026-05-26 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "v4m_product_match_rules"
down_revision: Union[str, Sequence[str], None] = "5d59c7faa3b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_match_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("pattern_type", sa.String(length=20), nullable=False),
        sa.Column("pattern_value", sa.String(length=500), nullable=False),
        sa.Column("canonical_category_id", sa.String(length=100), nullable=True),
        sa.Column("canonical_product_id", sa.Integer(), nullable=True),
        sa.Column("trust", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(length=100), nullable=False, server_default="admin"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("pattern_type IN ('exact', 'normalized', 'regex')", name="ck_product_match_rule_pattern_type"),
        sa.CheckConstraint("trust >= 0 AND trust <= 2", name="ck_product_match_rule_trust"),
        sa.ForeignKeyConstraint(["canonical_category_id"], ["unified_categories.id"]),
        sa.ForeignKeyConstraint(["canonical_product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pattern_type", "pattern_value", name="uq_product_match_rule_pattern"),
    )
    op.create_index("ix_product_match_rules_pattern", "product_match_rules", ["pattern_type", "pattern_value"], unique=False)
    op.create_index("ix_product_match_rules_category", "product_match_rules", ["canonical_category_id"], unique=False)
    op.create_index("ix_product_match_rules_product", "product_match_rules", ["canonical_product_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_product_match_rules_product", table_name="product_match_rules")
    op.drop_index("ix_product_match_rules_category", table_name="product_match_rules")
    op.drop_index("ix_product_match_rules_pattern", table_name="product_match_rules")
    op.drop_table("product_match_rules")
