"""Link catalog keyword definitions to the UnifiedCategory SSOT.

Revision ID: capstone_keyword_ssot_v1
Revises: capstone_ssot_v1
"""
from alembic import op
import sqlalchemy as sa


revision = "capstone_keyword_ssot_v1"
down_revision = "capstone_ssot_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable preserves the legacy autocomplete rows until the reviewed
    # catalog bundle attaches them to the new taxonomy.
    with op.batch_alter_table("keywords") as batch:
        batch.add_column(sa.Column("unified_category_id", sa.String(100), nullable=True))
        batch.create_foreign_key(
            "fk_keywords_unified_category",
            "unified_categories",
            ["unified_category_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_keywords_unified_category_id", ["unified_category_id"])


def downgrade() -> None:
    with op.batch_alter_table("keywords") as batch:
        batch.drop_index("ix_keywords_unified_category_id")
        batch.drop_constraint("fk_keywords_unified_category", type_="foreignkey")
        batch.drop_column("unified_category_id")
