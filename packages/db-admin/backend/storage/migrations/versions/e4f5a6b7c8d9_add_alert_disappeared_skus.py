"""add_alert_disappeared_skus

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-07-15 00:00:00.000000

주간 diff 결과로 사라진 SKU를 기록하는 alert 테이블.
매주 크롤링 갱신 시 이전 window에 있다가 당주 window에서 빠진 source_record_key를 삽입하고,
운영자가 확인·처리하면 resolved_at을 설정한다.

설계 원칙:
  - open alert(resolved_at IS NULL) 중복 방지는 애플리케이션 레벨에서 관리
  - mart + source_record_key 복합 인덱스로 open alert 조회 최적화
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, Sequence[str], None] = "d3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "alert_disappeared_skus",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True, nullable=False),
        sa.Column("mart", sa.String(120), nullable=False),
        sa.Column("source_record_key", sa.String(255), nullable=False),
        sa.Column("last_seen_title", sa.Text, nullable=True),
        sa.Column("last_seen_price", sa.Integer, nullable=True),
        sa.Column("last_captured_at", sa.DateTime, nullable=True),
        sa.Column("detected_at", sa.DateTime, nullable=False),
        sa.Column("resolved_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_alert_sku_mart_key", "alert_disappeared_skus", ["mart", "source_record_key"])
    op.create_index("ix_alert_sku_detected", "alert_disappeared_skus", ["detected_at"])
    op.create_index("ix_alert_sku_resolved", "alert_disappeared_skus", ["resolved_at"])


def downgrade() -> None:
    op.drop_index("ix_alert_sku_resolved", table_name="alert_disappeared_skus")
    op.drop_index("ix_alert_sku_detected", table_name="alert_disappeared_skus")
    op.drop_index("ix_alert_sku_mart_key", table_name="alert_disappeared_skus")
    op.drop_table("alert_disappeared_skus")
