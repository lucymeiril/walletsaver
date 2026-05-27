"""RD8 D-verify: products.canonical_product_id 컬럼 추가 (누락 보정)

Revision ID: f4d5e6f7a8b9
Revises: f3c4d5e6f7a8
Create Date: 2026-07-25 00:00:00.000000

문제:
    models.py에 canonical_product_id (self-FK, SET NULL) 컬럼이 정의되어 있으나
    f1a2b3c4d5e6 마이그레이션에서 누락되어 DB에 존재하지 않음.
    bundle_import.py apply_products()가 SELECT시 즉시 OperationalError 발생.

수정:
    products 테이블에 canonical_product_id INTEGER FK 컬럼 추가.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "f3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("products") as batch_op:
        batch_op.add_column(
            sa.Column(
                "canonical_product_id",
                sa.Integer(),
                nullable=True,
                comment="정규 대표 product id (self-FK). 동일 품목 variant 묶음용.",
            )
        )
        batch_op.create_index("ix_products_canonical_product_id", ["canonical_product_id"])
    # FK는 SQLite에서 runtime-enforced가 아니므로 별도 create_foreign_key 불필요


def downgrade() -> None:
    with op.batch_alter_table("products") as batch_op:
        batch_op.drop_index("ix_products_canonical_product_id")
        batch_op.drop_column("canonical_product_id")
