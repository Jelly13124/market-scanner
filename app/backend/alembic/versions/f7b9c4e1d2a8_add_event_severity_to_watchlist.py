"""add_event_severity_to_watchlist_entries

Revision ID: f7b9c4e1d2a8
Revises: e1f5a8c3b4d7
Create Date: 2026-05-14 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7b9c4e1d2a8'
down_revision: Union[str, None] = 'e1f5a8c3b4d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'watchlist_entries',
        sa.Column('event_severity', sa.Float(), nullable=False, server_default='0.0'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('watchlist_entries', 'event_severity')
