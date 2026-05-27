"""RD8 L3: imports_audit, category_review_queue, matching_entries.aliases 추가

Revision ID: a1b2c3d4e5f6
Revises: f3c4d5e6f7a8
Create Date: 2026-07-24 00:00:00.000000

변경 내용:
  - matching_entries: aliases(JSON) 컬럼 추가
  - imports_audit 테이블 신규 생성
  - category_review_queue 테이블 신규 생성
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # matching_entries: aliases 추가 (병행 브랜치 h6a7b8c9d0e1에서도 추가하므로 idempotent 처리)
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_cols = {c["name"] for c in insp.get_columns("matching_entries")}
    if "aliases" not in existing_cols:
        op.add_column(
            "matching_entries",
            sa.Column("aliases", sa.JSON(), nullable=True, comment="표기 변형 목록. JSON list[str]. 최대 50개."),
        )

    # imports_audit 테이블
    op.create_table(
        "imports_audit",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("file_type", sa.String(30), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("importer", sa.String(255), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("passed_rows", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("applied_counts", sa.JSON(), nullable=True),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_imports_audit_file_hash", "imports_audit", ["file_hash"])
    op.create_index("ix_imports_audit_timestamp", "imports_audit", ["timestamp"])
    op.create_index("ix_imports_audit_file_type", "imports_audit", ["file_type"])

    # category_review_queue 테이블
    op.create_table(
        "category_review_queue",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("proposed_id", sa.String(100), nullable=False),
        sa.Column("parent_id", sa.String(100), nullable=True),
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column("label_en", sa.String(200), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("similar_existing", sa.JSON(), nullable=True),
        sa.Column("source_file_hash", sa.String(64), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewer", sa.String(255), nullable=True),
        sa.UniqueConstraint("proposed_id", "source_file_hash", name="uq_cat_review_proposal"),
    )
    op.create_index("ix_cat_review_status", "category_review_queue", ["status"])
    op.create_index("ix_cat_review_proposed_id", "category_review_queue", ["proposed_id"])


def downgrade() -> None:
    op.drop_index("ix_cat_review_proposed_id", table_name="category_review_queue")
    op.drop_index("ix_cat_review_status", table_name="category_review_queue")
    op.drop_table("category_review_queue")

    op.drop_index("ix_imports_audit_file_type", table_name="imports_audit")
    op.drop_index("ix_imports_audit_timestamp", table_name="imports_audit")
    op.drop_index("ix_imports_audit_file_hash", table_name="imports_audit")
    op.drop_table("imports_audit")

    op.drop_column("matching_entries", "aliases")
