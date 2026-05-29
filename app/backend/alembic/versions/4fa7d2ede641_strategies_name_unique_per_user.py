"""strategies name unique per-user

Revision ID: 4fa7d2ede641
Revises: 591dc9226a2d
Create Date: 2026-05-29 16:28:59.853589

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4fa7d2ede641'
down_revision: Union[str, None] = '591dc9226a2d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Replace the global-unique strategies.name index with a per-user composite unique."""
    with op.batch_alter_table("strategies", schema=None) as batch_op:
        batch_op.drop_index("ix_strategies_name")  # was UNIQUE(name) — global
        batch_op.create_unique_constraint("uq_strategy_user_name", ["user_id", "name"])
        batch_op.create_index("ix_strategies_name", ["name"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("strategies", schema=None) as batch_op:
        batch_op.drop_index("ix_strategies_name")
        batch_op.drop_constraint("uq_strategy_user_name", type_="unique")
        batch_op.create_index("ix_strategies_name", ["name"], unique=True)
