"""Restore the retired Round R G5-c revision as a no-op bridge.

Revision ID: r_g5c_opinet
Revises: g5b0hotdeal

The original revision created OPINET tables inside the main DB. OPINET now owns a
separate SQLite store, so new main databases must not recreate those retired
tables. Keeping the historical revision ID preserves the Alembic graph for both
existing databases that already recorded this revision and fresh databases.
"""
from typing import Sequence, Union

revision: str = "r_g5c_opinet"
down_revision: Union[str, Sequence[str], None] = "g5b0hotdeal"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
