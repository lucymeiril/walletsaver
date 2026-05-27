"""rd8_heads_merge

Revision ID: 306077c6d0e2
Revises: a1b2c3d4e5f6, h7b8c9d0e1f2
Create Date: 2026-05-26 01:56:35.773373

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '306077c6d0e2'
down_revision: Union[str, Sequence[str], None] = ('a1b2c3d4e5f6', 'h7b8c9d0e1f2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
