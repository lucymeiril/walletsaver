"""RD8 D1: Product 정규화 컬럼 추가

Revision ID: f1a2b3c4d5e6
Revises: e4f5a6b7c8d9
Create Date: 2026-07-23 00:00:00.000000

변경 내용:
  - products: brand, name_core, pack_qty, pack_unit, unit_kind, display_name,
              source_marts, aliases 추가
  - UNIQUE constraint uq_product_canonical (brand, name_core, pack_qty, pack_unit) 추가
  - 기존 800건 dirty 데이터 삭제 (fixture 가짜 데이터, 재구축 대상)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e4f5a6b7c8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # baseline_prices는 products FK에 CASCADE 삭제이므로 products 삭제 전에 먼저 삭제
    op.execute("DELETE FROM baseline_prices")
    op.execute("DELETE FROM products")

    op.add_column("products", sa.Column("brand", sa.String(200), nullable=True,
                                        comment="브랜드명"))
    op.add_column("products", sa.Column("name_core", sa.String(500), nullable=True,
                                        comment="상품 핵심명"))
    op.add_column("products", sa.Column("pack_qty", sa.Float(), nullable=True,
                                        comment="용량/수량 숫자"))
    op.add_column("products", sa.Column("pack_unit", sa.String(50), nullable=True,
                                        comment="용량 단위"))
    op.add_column("products", sa.Column("unit_kind", sa.String(20), nullable=True,
                                        comment="단위 분류: weight|volume|count|pack"))
    op.add_column("products", sa.Column("display_name", sa.String(400), nullable=True,
                                        comment="UI 표시명 캐시"))
    op.add_column("products", sa.Column("source_marts", sa.JSON(), nullable=True,
                                        comment="수집 마트 코드 캐시"))
    op.add_column("products", sa.Column("aliases", sa.JSON(), nullable=True,
                                        comment="동일 상품 다른 표기명 목록"))

    # SQLite: UNIQUE constraint는 batch_alter_table 사용
    with op.batch_alter_table("products") as batch_op:
        batch_op.create_unique_constraint(
            "uq_product_canonical",
            ["brand", "name_core", "pack_qty", "pack_unit"],
        )

    op.create_index("ix_products_brand", "products", ["brand"])
    op.create_index("ix_products_name_core", "products", ["name_core"])
    op.create_index("ix_products_unit_kind", "products", ["unit_kind"])


def downgrade() -> None:
    op.drop_index("ix_products_unit_kind", table_name="products")
    op.drop_index("ix_products_name_core", table_name="products")
    op.drop_index("ix_products_brand", table_name="products")
    with op.batch_alter_table("products") as batch_op:
        batch_op.drop_constraint("uq_product_canonical", type_="unique")
    for col in ["aliases", "source_marts", "display_name", "unit_kind",
                "pack_unit", "pack_qty", "name_core", "brand"]:
        op.drop_column("products", col)
