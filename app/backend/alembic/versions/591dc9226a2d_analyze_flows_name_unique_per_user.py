"""analyze_flows name unique per-user

Revision ID: 591dc9226a2d
Revises: 17da9147c7cb
Create Date: 2026-05-29 16:12:32.889395

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '591dc9226a2d'
down_revision: Union[str, None] = '17da9147c7cb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Replace the global-unique analyze_flows.name index with a per-user composite unique."""
    with op.batch_alter_table("analyze_flows", schema=None) as batch_op:
        batch_op.drop_index("ix_analyze_flows_name")  # was UNIQUE(name) — global
        batch_op.create_unique_constraint("uq_analyze_flow_user_name", ["user_id", "name"])
        batch_op.create_index("ix_analyze_flows_name", ["name"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("analyze_flows", schema=None) as batch_op:
        batch_op.drop_index("ix_analyze_flows_name")
        batch_op.drop_constraint("uq_analyze_flow_user_name", type_="unique")
        batch_op.create_index("ix_analyze_flows_name", ["name"], unique=True)
