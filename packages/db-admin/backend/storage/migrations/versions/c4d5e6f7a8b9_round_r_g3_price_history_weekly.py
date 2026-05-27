"""Round R G3: weekly price_history uniqueness

Revision ID: c4d5e6f7a8b9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-26 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("price_history") as batch_op:
        batch_op.add_column(sa.Column("product_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("week_of", sa.Date(), nullable=True))
        batch_op.create_foreign_key("fk_price_history_product_id", "products", ["product_id"], ["id"])

    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "sqlite":
        bind.execute(sa.text("""
            UPDATE price_history
            SET week_of = date(observed_at, '-' || ((CAST(strftime('%w', observed_at) AS INTEGER) + 6) % 7) || ' days')
            WHERE week_of IS NULL
        """))
    elif dialect == "postgresql":
        bind.execute(sa.text("UPDATE price_history SET week_of = date_trunc('week', observed_at)::date WHERE week_of IS NULL"))

    op.create_index("ix_price_history_product_id", "price_history", ["product_id"])
    op.create_index("ix_price_history_week_of", "price_history", ["week_of"])
    op.create_index("ix_price_history_product_week", "price_history", ["product_id", "week_of"])
    with op.batch_alter_table("price_history") as batch_op:
        batch_op.create_unique_constraint("uq_price_history_product_week_mart", ["product_id", "week_of", "mart"])


def downgrade() -> None:
    with op.batch_alter_table("price_history") as batch_op:
        batch_op.drop_constraint("uq_price_history_product_week_mart", type_="unique")
    op.drop_index("ix_price_history_product_week", table_name="price_history")
    op.drop_index("ix_price_history_week_of", table_name="price_history")
    op.drop_index("ix_price_history_product_id", table_name="price_history")
    with op.batch_alter_table("price_history") as batch_op:
        batch_op.drop_constraint("fk_price_history_product_id", type_="foreignkey")
        batch_op.drop_column("week_of")
        batch_op.drop_column("product_id")
