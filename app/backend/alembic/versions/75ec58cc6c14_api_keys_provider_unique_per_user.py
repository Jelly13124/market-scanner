"""api_keys provider unique per-user

Revision ID: 75ec58cc6c14
Revises: 4fa7d2ede641
Create Date: 2026-05-29 22:20:51.870507

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '75ec58cc6c14'
down_revision: Union[str, None] = '4fa7d2ede641'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Replace the global-unique api_keys.provider index with a per-user composite unique."""
    with op.batch_alter_table("api_keys", schema=None) as batch_op:
        batch_op.drop_index("ix_api_keys_provider")  # was UNIQUE(provider) — global
        batch_op.create_unique_constraint("uq_api_key_user_provider", ["user_id", "provider"])
        batch_op.create_index("ix_api_keys_provider", ["provider"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("api_keys", schema=None) as batch_op:
        batch_op.drop_index("ix_api_keys_provider")
        batch_op.drop_constraint("uq_api_key_user_provider", type_="unique")
        batch_op.create_index("ix_api_keys_provider", ["provider"], unique=True)
