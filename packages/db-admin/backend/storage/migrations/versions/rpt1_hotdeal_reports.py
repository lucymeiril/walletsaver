"""Preserve the retired local hotdeal-report revision as a no-op bridge.

Revision ID: rpt1_hotdeal_reports
Revises: w5c_catalog_sync_log

Authenticated user reports now belong to the deployed web-api's persistent
interactions database. The local db-admin source database must not recreate that
server-owned state on fresh checkouts. Keeping this historical revision ID
preserves Alembic history for databases that already recorded it.
"""
from typing import Sequence, Union

revision: str = "rpt1_hotdeal_reports"
down_revision: Union[str, Sequence[str], None] = "w5c_catalog_sync_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
