"""RD8 C4: categories 시드 컬럼 추가 + matching_entries source enum 확장

Revision ID: h6a7b8c9d0e1
Revises: g5e6f7a8b9c0
Create Date: 2026-07-28 00:00:00.000000

변경 내용:
  1. categories 테이블: RD8 C4 시드 적재용 컬럼 추가
     - display_name_ko  VARCHAR(200)  NULLABLE  한국어 표시명 (예: "잎채소·쌈채소")
     - unit_kind_default VARCHAR(20)  NULLABLE  기본 단위 종류 (weight|volume|count|pack)
     - keyword_seeds    JSON         NULLABLE  검색/분류 초기 키워드 목록 (list[str])
     - notes            TEXT         NULLABLE  분류 결정 근거·운영 메모
     - source           VARCHAR(30)  NULLABLE  출처 ('rd8_seed'|'external_llm'|'manual')
     - created_at       DATETIME     NULLABLE  생성일시
     - updated_at       DATETIME     NULLABLE  수정일시
  2. matching_entries 테이블: source CHECK constraint 확장
     - 기존: 'crawler-auto' | 'human' | 'external-ai'
     - 추가: 'rd8_c3_seed'  (RD8 C3 시뮬레이션 검증 시드)
     - SQLite는 CHECK constraint 수정 시 테이블 재생성이 필요하므로
       batch_alter_table (recreate_table) 전략 사용
"""
from typing import Sequence, Union
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision: str = "h6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "g5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. categories: 신규 컬럼 추가 ───────────────────────────────────────────
    op.add_column("categories", sa.Column("display_name_ko", sa.String(200), nullable=True,
                                          comment="한국어 표시명 (예: 잎채소·쌈채소)"))
    op.add_column("categories", sa.Column("unit_kind_default", sa.String(20), nullable=True,
                                          comment="기본 단위 종류: weight|volume|count|pack"))
    op.add_column("categories", sa.Column("keyword_seeds", sa.JSON(), nullable=True,
                                          comment="검색/분류 초기 키워드 목록 (list[str])"))
    op.add_column("categories", sa.Column("notes", sa.Text(), nullable=True,
                                          comment="분류 결정 근거·운영 메모"))
    op.add_column("categories", sa.Column("source", sa.String(30), nullable=True,
                                          comment="출처: rd8_seed | external_llm | manual"))
    op.add_column("categories", sa.Column("created_at", sa.DateTime(), nullable=True))
    op.add_column("categories", sa.Column("updated_at", sa.DateTime(), nullable=True))

    op.create_index("ix_categories_source", "categories", ["source"])
    op.create_index("ix_categories_active", "categories", ["is_active"])

    # ── 2. matching_entries: source CHECK constraint 확장 (SQLite batch recreate) ──
    # SQLite는 ADD CONSTRAINT를 지원하지 않으므로 batch_alter_table(recreate=True)로
    # 테이블을 통째로 재생성해 새 CHECK constraint를 적용한다.
    # 운영 PostgreSQL에서는 DROP + ADD CONSTRAINT로 처리되므로 이 방식은 SQLite 전용.
    with op.batch_alter_table("matching_entries", recreate="auto") as batch_op:
        batch_op.drop_constraint("ck_matching_source_enum", type_="check")
        batch_op.create_check_constraint(
            "ck_matching_source_enum",
            "source IN ('crawler-auto', 'human', 'external-ai', 'rd8_c3_seed')",
        )


def downgrade() -> None:
    # ── 2. matching_entries: source CHECK constraint 롤백 ───────────────────────
    with op.batch_alter_table("matching_entries", recreate="auto") as batch_op:
        batch_op.drop_constraint("ck_matching_source_enum", type_="check")
        batch_op.create_check_constraint(
            "ck_matching_source_enum",
            "source IN ('crawler-auto', 'human', 'external-ai')",
        )

    # ── 1. categories: 신규 컬럼 제거 ───────────────────────────────────────────
    op.drop_index("ix_categories_active", table_name="categories")
    op.drop_index("ix_categories_source", table_name="categories")
    op.drop_column("categories", "updated_at")
    op.drop_column("categories", "created_at")
    op.drop_column("categories", "source")
    op.drop_column("categories", "notes")
    op.drop_column("categories", "keyword_seeds")
    op.drop_column("categories", "unit_kind_default")
    op.drop_column("categories", "display_name_ko")
