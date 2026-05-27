"""Round S: product promo label/type columns

Revision ID: s_emart_promo
Revises: c5e6f7a8b9c0
Create Date: 2026-05-26 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "s_emart_promo"
down_revision: Union[str, Sequence[str], None] = "c5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("products") as batch_op:
        batch_op.add_column(sa.Column("promo_label", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("promo_type", sa.String(length=40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("products") as batch_op:
        batch_op.drop_column("promo_type")
        batch_op.drop_column("promo_label")
