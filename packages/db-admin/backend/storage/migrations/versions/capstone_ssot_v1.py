"""Capstone catalog SSOT links.

Revision ID: capstone_ssot_v1
Revises: rpt1_hotdeal_reports
"""
from alembic import op
import sqlalchemy as sa


revision = "capstone_ssot_v1"
down_revision = "rpt1_hotdeal_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("normalized_canonical_products") as batch:
        batch.add_column(sa.Column("unified_category_id", sa.String(100), nullable=True))
        batch.create_foreign_key(
            "fk_norm_product_unified_category",
            "unified_categories",
            ["unified_category_id"],
            ["id"],
        )
        batch.create_index("ix_normalized_canonical_products_unified_category_id", ["unified_category_id"])

    with op.batch_alter_table("matching_entries") as batch:
        batch.add_column(sa.Column("public_product_id", sa.String(120), nullable=True))
        batch.add_column(sa.Column("public_variant_id", sa.String(120), nullable=True))
        batch.create_foreign_key(
            "fk_matching_public_product",
            "normalized_canonical_products",
            ["public_product_id"],
            ["public_product_id"],
        )
        batch.create_foreign_key(
            "fk_matching_public_variant",
            "normalized_product_variants",
            ["public_variant_id"],
            ["public_variant_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("matching_entries") as batch:
        batch.drop_constraint("fk_matching_public_variant", type_="foreignkey")
        batch.drop_constraint("fk_matching_public_product", type_="foreignkey")
        batch.drop_column("public_variant_id")
        batch.drop_column("public_product_id")

    with op.batch_alter_table("normalized_canonical_products") as batch:
        batch.drop_index("ix_normalized_canonical_products_unified_category_id")
        batch.drop_constraint("fk_norm_product_unified_category", type_="foreignkey")
        batch.drop_column("unified_category_id")
