"""watchlist name unique per-user

Revision ID: 5943ff1fb78d
Revises: 359c3b216a47
Create Date: 2026-05-29 16:03:15.350917

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5943ff1fb78d'
down_revision: Union[str, None] = '359c3b216a47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Replace the global-unique name index with a per-user composite unique."""
    with op.batch_alter_table("user_watchlists", schema=None) as batch_op:
        batch_op.drop_index("ix_user_watchlists_name")  # was UNIQUE(name) — global
        batch_op.create_unique_constraint("uq_user_watchlist_user_name", ["user_id", "name"])
        batch_op.create_index("ix_user_watchlists_name", ["name"], unique=False)


def downgrade() -> None:
    """Restore the global-unique name index."""
    with op.batch_alter_table("user_watchlists", schema=None) as batch_op:
        batch_op.drop_index("ix_user_watchlists_name")
        batch_op.drop_constraint("uq_user_watchlist_user_name", type_="unique")
        batch_op.create_index("ix_user_watchlists_name", ["name"], unique=True)
