"""add_matching_entries

Revision ID: d3e4f5a6b7c8
Revises: c1a2b3d4e5f6
Create Date: 2026-07-01 00:00:00.000000

매칭 테이블 신설 — 새 크롤 파이프라인 지원.
crawler raw → matching_entries hit → DB 직행 / miss만 외부 LLM 분류 후 import.

설계 원칙:
  - match_key UNIQUE: 동일 정규화 결과 중복 방지
  - confidence CHECK [0,1]: 범위 위반은 알고리즘 버그 신호이므로 DB 레벨 차단
  - source CHECK enum: 외부 import 시 오타 차단
  - category_id: categories.id FK (String — categories PK가 문자열임)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, Sequence[str], None] = "c1a2b3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """matching_entries 테이블 생성."""
    op.create_table(
        "matching_entries",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True, nullable=False),

        # match_key: brand|name_core|pack_qty|pack_unit 정규화 결과 (UNIQUE)
        sa.Column("match_key", sa.Text, nullable=False, unique=True),

        # 디버깅용 분해 필드
        sa.Column("brand", sa.String(200), nullable=True),
        sa.Column("name_core", sa.String(500), nullable=True),
        sa.Column("pack_qty", sa.Float, nullable=True),
        sa.Column("pack_unit", sa.String(50), nullable=True),

        # canonical_product_id: soft reference (FK 미적용 — CanonicalBase 분리)
        sa.Column("canonical_product_id", sa.String(40), nullable=True),

        # category_id: categories.id FK (String — categories PK가 문자열)
        sa.Column(
            "category_id",
            sa.String(100),
            sa.ForeignKey("categories.id"),
            nullable=True,
        ),

        # keyword_ids: list[int] JSON
        sa.Column("keyword_ids", sa.JSON, nullable=True),

        # confidence [0,1] — CHECK constraint 절대 제거 금지
        sa.Column("confidence", sa.Float, nullable=False, server_default="1.0"),

        # source enum — CHECK constraint 절대 제거 금지
        sa.Column("source", sa.String(20), nullable=False),

        # 타임스탬프 (UTC)
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),

        # hit_count: pipeline hit 횟수
        sa.Column("hit_count", sa.Integer, nullable=False, server_default="0"),

        # notes: 운영자 메모
        sa.Column("notes", sa.Text, nullable=True),

        # CHECK: confidence 범위 [0,1] — 절대 제거 금지
        sa.CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_matching_confidence_range",
        ),
        # CHECK: source enum 허용값 — 절대 제거 금지
        sa.CheckConstraint(
            "source IN ('crawler-auto', 'human', 'external-ai')",
            name="ck_matching_source_enum",
        ),
    )

    # match_key unique index (column unique=True가 생성하지만 명시적 index도 생성)
    op.create_index("ix_matching_match_key", "matching_entries", ["match_key"], unique=True)
    op.create_index("ix_matching_category", "matching_entries", ["category_id"])
    op.create_index("ix_matching_source", "matching_entries", ["source"])


def downgrade() -> None:
    op.drop_index("ix_matching_source", table_name="matching_entries")
    op.drop_index("ix_matching_category", table_name="matching_entries")
    op.drop_index("ix_matching_match_key", table_name="matching_entries")
    op.drop_table("matching_entries")
