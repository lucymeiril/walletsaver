"""RD8 D1: BaselinePrice 마트 코드 + 정규화 단가 컬럼 추가

Revision ID: f2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-07-23 00:01:00.000000

변경 내용:
  - baseline_prices: mart_code, pack_qty_snapshot, pack_unit_snapshot,
                     unit_price_normalized, unit_price_basis 추가
  - UNIQUE constraint uq_baseline_product_mart_date 추가
  - 기존 source 값으로 mart_code 초기화
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("baseline_prices", sa.Column("mart_code", sa.String(50), nullable=True,
                                                comment="정규화된 마트 코드"))
    op.add_column("baseline_prices", sa.Column("pack_qty_snapshot", sa.Float(), nullable=True,
                                                comment="가격 수집 시점의 pack_qty"))
    op.add_column("baseline_prices", sa.Column("pack_unit_snapshot", sa.String(50), nullable=True,
                                                comment="가격 수집 시점의 pack_unit"))
    op.add_column("baseline_prices", sa.Column("unit_price_normalized", sa.Float(), nullable=True,
                                                comment="환산 단가. weight→원/100g, volume→원/100ml"))
    op.add_column("baseline_prices", sa.Column("unit_price_basis", sa.String(10), nullable=True,
                                                comment="정규화 기준 단위. 예: g, ml"))

    # 기존 source 값으로 mart_code 초기화 (데이터 있을 경우 하위호환)
    op.execute("UPDATE baseline_prices SET mart_code = source WHERE mart_code IS NULL")

    # SQLite: UNIQUE constraint는 batch_alter_table 사용
    with op.batch_alter_table("baseline_prices") as batch_op:
        batch_op.create_unique_constraint(
            "uq_baseline_product_mart_date",
            ["product_id", "mart_code", "recorded_at"],
        )
    op.create_index("ix_baseline_mart_code", "baseline_prices", ["mart_code"])
    op.create_index("ix_baseline_product_mart", "baseline_prices", ["product_id", "mart_code"])


def downgrade() -> None:
    op.drop_index("ix_baseline_product_mart", table_name="baseline_prices")
    op.drop_index("ix_baseline_mart_code", table_name="baseline_prices")
    with op.batch_alter_table("baseline_prices") as batch_op:
        batch_op.drop_constraint("uq_baseline_product_mart_date", type_="unique")
    for col in ["unit_price_basis", "unit_price_normalized",
                "pack_unit_snapshot", "pack_qty_snapshot", "mart_code"]:
        op.drop_column("baseline_prices", col)
