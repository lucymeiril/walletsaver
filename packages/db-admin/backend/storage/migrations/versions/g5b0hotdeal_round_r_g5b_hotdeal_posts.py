"""Round R G5-b: hotdeal source tables placeholder.

Revision ID: g5b0hotdeal
Revises: TODO after Round R G2 mapping head reconciliation
Create Date: 2026-05-26 00:00:00.000000

메인 브랜치에서 G2-mapping 완료 후 Alembic chain을 reconcile한다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g5b0hotdeal"
# TODO(Round R main reconcile): set to the post-G2 mapping head when c3d4e5f6a7b8 is merged.
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SOURCE_SITE_VALUES = ("algumon", "ppomppu", "fmkorea", "clien", "quasarzone", "arca", "cocodal", "other")


def upgrade() -> None:
    op.create_table(
        "hotdeal_posts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_site", sa.String(length=30), nullable=False),
        sa.Column("source_native_id", sa.String(length=100), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("posted_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("original_price", sa.Float(), nullable=True),
        sa.Column("discount_rate", sa.Float(), nullable=True),
        sa.Column("shop_name", sa.String(length=200), nullable=True),
        sa.Column("category_raw", sa.String(length=200), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("fetched_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("hash_dedup", sa.String(length=64), nullable=False),
        sa.CheckConstraint("source_site IN " + repr(SOURCE_SITE_VALUES), name="ck_hotdeal_posts_source_site"),
        sa.UniqueConstraint("hash_dedup", name="uq_hotdeal_posts_hash_dedup"),
    )
    op.create_index("ix_hotdeal_posts_source_native", "hotdeal_posts", ["source_site", "source_native_id"])
    op.create_index("ix_hotdeal_posts_posted_at", "hotdeal_posts", ["posted_at"])
    op.create_index("ix_hotdeal_posts_fetched_at", "hotdeal_posts", ["fetched_at"])
    op.create_index("ix_hotdeal_posts_active", "hotdeal_posts", ["is_active"])

    op.create_table(
        "hotdeal_comment_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("hotdeal_id", sa.Integer(), sa.ForeignKey("hotdeal_posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("comment_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("vote_up", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("vote_down", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("snapshot_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_hotdeal_comment_snapshots_hotdeal", "hotdeal_comment_snapshots", ["hotdeal_id", "snapshot_at"])


def downgrade() -> None:
    op.drop_index("ix_hotdeal_comment_snapshots_hotdeal", table_name="hotdeal_comment_snapshots")
    op.drop_table("hotdeal_comment_snapshots")
    op.drop_index("ix_hotdeal_posts_active", table_name="hotdeal_posts")
    op.drop_index("ix_hotdeal_posts_fetched_at", table_name="hotdeal_posts")
    op.drop_index("ix_hotdeal_posts_posted_at", table_name="hotdeal_posts")
    op.drop_index("ix_hotdeal_posts_source_native", table_name="hotdeal_posts")
    op.drop_table("hotdeal_posts")
