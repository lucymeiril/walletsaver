"""RD8 D1: MatchingEntry 확장 컬럼 추가

Revision ID: f3c4d5e6f7a8
Revises: f2b3c4d5e6f7
Create Date: 2026-07-23 00:02:00.000000

변경 내용:
  - matching_entries: pack_unit_kind, source_record_key 추가
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f3c4d5e6f7a8"
down_revision: Union[str, Sequence[str], None] = "f2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("matching_entries", sa.Column("pack_unit_kind", sa.String(20), nullable=True,
                                                 comment="단위 분류 캐시: weight|volume|count|pack"))
    op.add_column("matching_entries", sa.Column("source_record_key", sa.String(255), nullable=True,
                                                 comment="크롤러 원본 레코드 키. 멱등성 보장용."))
    op.create_index("ix_matching_unit_kind", "matching_entries", ["pack_unit_kind"])
    op.create_index("ix_matching_source_record_key", "matching_entries", ["source_record_key"])


def downgrade() -> None:
    op.drop_index("ix_matching_source_record_key", table_name="matching_entries")
    op.drop_index("ix_matching_unit_kind", table_name="matching_entries")
    op.drop_column("matching_entries", "source_record_key")
    op.drop_column("matching_entries", "pack_unit_kind")
