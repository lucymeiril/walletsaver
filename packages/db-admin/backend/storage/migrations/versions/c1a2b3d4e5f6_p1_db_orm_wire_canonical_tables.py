"""p1_db_orm_wire_canonical_tables

Revision ID: c1a2b3d4e5f6
Revises: 8018226a8e9e
Create Date: 2026-06-01 00:00:00.000000

p1-db-orm-wire: canonical_models.py (CanonicalBase) 를 Alembic 마이그레이션에 연결.
canonical_category_nodes, canonical_products, canonical_mart_sku_aliases,
canonical_price_observations, canonical_product_review_queue 5개 테이블 생성.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1a2b3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "8018226a8e9e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Canonical tables — fresh DB 로부터 실행 통과."""

    # ─── canonical_category_nodes ───────────────────────────────────────────
    op.create_table(
        "canonical_category_nodes",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("parent_id", sa.String(64), sa.ForeignKey("canonical_category_nodes.id"), nullable=True),
        sa.Column("name_kr", sa.String(200), nullable=False),
        sa.Column("name_slug", sa.String(200), nullable=False),
        sa.Column("level", sa.Integer, nullable=False),
        sa.Column("path", sa.String(500), nullable=False, unique=True),
        sa.Column("display_order", sa.Integer, default=0),
    )

    # ─── canonical_products ─────────────────────────────────────────────────
    op.create_table(
        "canonical_products",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("brand", sa.String(200), nullable=True),
        sa.Column("name_core", sa.String(500), nullable=False),
        sa.Column("pack_quantity", sa.Float, nullable=False, default=1.0),
        sa.Column("pack_unit", sa.String(50), nullable=False, default="개"),
        sa.Column(
            "category_path_internal_id",
            sa.String(64),
            sa.ForeignKey("canonical_category_nodes.id"),
            nullable=True,
        ),
        sa.Column("representative_image_url", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    # ─── canonical_mart_sku_aliases ─────────────────────────────────────────
    # mart enum: SQLite 에서는 VARCHAR, PostgreSQL 에서는 native enum.
    op.create_table(
        "canonical_mart_sku_aliases",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column(
            "canonical_id",
            sa.String(40),
            sa.ForeignKey("canonical_products.id"),
            nullable=False,
        ),
        sa.Column("mart", sa.String(32), nullable=False),
        sa.Column("mart_item_id", sa.String(200), nullable=False),
        sa.Column("mart_item_name_raw", sa.Text, nullable=False),
        sa.Column("source_url", sa.Text, nullable=True),
        sa.Column("first_seen_at", sa.DateTime, nullable=False),
        sa.Column("last_seen_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("mart", "mart_item_id", name="uq_mart_sku"),
    )

    # ─── canonical_price_observations ───────────────────────────────────────
    op.create_table(
        "canonical_price_observations",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column(
            "canonical_id",
            sa.String(40),
            sa.ForeignKey("canonical_products.id"),
            nullable=False,
        ),
        sa.Column("mart", sa.String(32), nullable=False),
        sa.Column("regular_price", sa.Integer, nullable=True),
        sa.Column("sale_price", sa.Integer, nullable=False),
        sa.Column("on_sale", sa.Boolean, nullable=False),
        sa.Column("discount_rate", sa.Integer, nullable=True),
        sa.Column("unit_price_normalized", sa.Float, nullable=True),
        sa.Column("unit_price_basis", sa.String(20), nullable=False, default="unknown"),
        sa.Column("observed_at", sa.DateTime, nullable=False),
        sa.Column("source_url", sa.Text, nullable=True),
        sa.Column("raw_payload_hash", sa.String(40), nullable=False),
        sa.Column("event_labels", sa.JSON, nullable=True),
    )
    op.create_index(
        "ix_price_obs_canonical_mart_time",
        "canonical_price_observations",
        ["canonical_id", "mart", "observed_at"],
    )

    # ─── canonical_product_review_queue ─────────────────────────────────────
    op.create_table(
        "canonical_product_review_queue",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("raw_payload", sa.JSON, nullable=False),
        sa.Column("source_mart", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column(
            "suggested_canonical_id",
            sa.String(40),
            sa.ForeignKey("canonical_products.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("resolved_at", sa.DateTime, nullable=True),
        sa.Column("resolver_user_id", sa.String(200), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("canonical_product_review_queue")
    op.drop_index("ix_price_obs_canonical_mart_time", table_name="canonical_price_observations")
    op.drop_table("canonical_price_observations")
    op.drop_table("canonical_mart_sku_aliases")
    op.drop_table("canonical_products")
    op.drop_table("canonical_category_nodes")
