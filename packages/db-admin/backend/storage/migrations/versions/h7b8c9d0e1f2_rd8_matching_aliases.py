"""RD8 C4 fixup: matching_entries.aliases 컬럼 추가 (스키마 드리프트 수정)

Revision ID: h7b8c9d0e1f2
Revises: h6a7b8c9d0e1
Create Date: 2026-07-28 00:01:00.000000

변경 내용:
  - matching_entries.aliases: JSON 컬럼 추가.
    models.py의 MatchingEntry.aliases가 이미 정의돼 있었으나
    대응 마이그레이션이 누락된 스키마 드리프트를 수정한다.
    f3c4d5e6f7a8 (rd8_matching_entry_extensions)에서 pack_unit_kind,
    source_record_key만 추가하고 aliases를 빠뜨린 것이 원인.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "h7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "h6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "matching_entries",
        sa.Column(
            "aliases",
            sa.JSON(),
            nullable=True,
            comment="동일 항목의 표기 변형 목록. JSON list[str]. 최대 50개.",
        ),
    )
    op.create_index("ix_matching_aliases_null", "matching_entries", ["aliases"])


def downgrade() -> None:
    op.drop_index("ix_matching_aliases_null", table_name="matching_entries")
    op.drop_column("matching_entries", "aliases")
