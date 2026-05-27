"""Round R: relax product canonical uniqueness across marts.

Revision ID: c5e6f7a8b9c0
Revises: r_g5c_opinet
Create Date: 2026-05-26 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "c5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "r_g5c_opinet"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("products") as batch_op:
        batch_op.drop_constraint("uq_product_canonical", type_="unique")
        batch_op.create_unique_constraint(
            "uq_products_mart_native",
            ["mart", "mart_native_code"],
        )


def downgrade() -> None:
    with op.batch_alter_table("products") as batch_op:
        batch_op.drop_constraint("uq_products_mart_native", type_="unique")
        batch_op.create_unique_constraint(
            "uq_product_canonical",
            ["brand", "name_core", "pack_qty", "pack_unit"],
        )
