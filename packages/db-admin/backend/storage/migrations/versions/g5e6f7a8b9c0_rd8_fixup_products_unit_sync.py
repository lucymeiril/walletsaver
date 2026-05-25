"""RD8 D-fixup Fix-2: products.unit → pack_unit 동기화 (데이터 패치)

Revision ID: g5e6f7a8b9c0
Revises: f4d5e6f7a8b9
Create Date: 2026-07-26 00:00:00.000000

변경 내용:
  - products.unit 레거시 컬럼을 pack_unit 값으로 동기화.
    bundle_import에서 신규 생성 시 unit=pack_unit으로 설정되지 않았던 기존 rows 패치.
  - pack_unit IS NULL이면 'EA' 유지 (기존 default '개'도 그대로).
  - 이 마이그레이션 이후 bundle_import.apply_products()는 항상 unit=canon_unit으로 설정한다.

정책 (models.py Product 참조):
  unit은 레거시 호환 컬럼.
  신규 코드는 pack_unit / pack_unit_kind 를 사용할 것.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "g5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "f4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pack_unit이 있는 products에서 unit != pack_unit 인 rows를 패치
    op.execute("""
        UPDATE products
        SET unit = pack_unit
        WHERE pack_unit IS NOT NULL AND unit != pack_unit
    """)
    # pack_unit이 없는 rows는 현재 unit 그대로 (기본값 '개' 또는 'EA' 유지)


def downgrade() -> None:
    # unit 컬럼의 원래 값 복원 불가 (단방향 패치)
    # 필요 시 backup에서 복구
    pass
