"""Round R G1: product native code/canon hash/external seller/unit price columns + price_history table

Revision ID: b2c3d4e5f6a7
Revises: 306077c6d0e2
Create Date: 2026-05-26 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "306077c6d0e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PRODUCT_COLUMNS = (
    "mart",
    "mart_native_code",
    "canon_hash",
    "external_seller",
    "unit_price_displayed",
    "unit_price_basis_raw",
    "mart_native_category_id",
    "mart_native_category_path",
    "canonical_url",
    "mart_internal_seller_id",
)


def upgrade() -> None:
    with op.batch_alter_table("products") as batch_op:
        batch_op.add_column(sa.Column("mart", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("mart_native_code", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("canon_hash", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("external_seller", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("unit_price_displayed", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("unit_price_basis_raw", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("mart_native_category_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("mart_native_category_path", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("canonical_url", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("mart_internal_seller_id", sa.String(length=64), nullable=True))

    op.create_index("ix_products_mart", "products", ["mart"])
    op.create_index("ix_products_mart_native_code", "products", ["mart_native_code"])
    op.create_index("ix_products_canon_hash", "products", ["canon_hash"])
    op.create_index("ix_products_mart_native_category_id", "products", ["mart_native_category_id"])
    op.create_index("ix_products_mart_native", "products", ["mart", "mart_native_code"])

    op.create_table(
        "price_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("mart", sa.String(length=20), nullable=False),
        sa.Column("canon_key", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("sale_price", sa.Float(), nullable=True),
        sa.Column("unit_price", sa.Float(), nullable=True),
        sa.Column("period_start", sa.DateTime(), nullable=True),
        sa.Column("period_end", sa.DateTime(), nullable=True),
        sa.Column("source_run_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("mart", "canon_key", "observed_at", name="uq_price_history_mart_canon_observed"),
    )
    op.create_index("ix_price_history_mart", "price_history", ["mart"])
    op.create_index("ix_price_history_canon_key", "price_history", ["canon_key"])
    op.create_index("ix_price_history_observed_at", "price_history", ["observed_at"])
    op.create_index("ix_price_history_mart_canon_observed", "price_history", ["mart", "canon_key", sa.text("observed_at DESC")])


def downgrade() -> None:
    op.drop_index("ix_price_history_mart_canon_observed", table_name="price_history")
    op.drop_index("ix_price_history_observed_at", table_name="price_history")
    op.drop_index("ix_price_history_canon_key", table_name="price_history")
    op.drop_index("ix_price_history_mart", table_name="price_history")
    op.drop_table("price_history")

    op.drop_index("ix_products_mart_native", table_name="products")
    op.drop_index("ix_products_mart_native_category_id", table_name="products")
    op.drop_index("ix_products_canon_hash", table_name="products")
    op.drop_index("ix_products_mart_native_code", table_name="products")
    op.drop_index("ix_products_mart", table_name="products")

    with op.batch_alter_table("products") as batch_op:
        for column_name in reversed(PRODUCT_COLUMNS):
            batch_op.drop_column(column_name)
