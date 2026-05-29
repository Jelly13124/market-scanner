"""add user_id to screener_presets + backfill

Revision ID: 17da9147c7cb
Revises: 5943ff1fb78d
Create Date: 2026-05-29 16:12:30.216295

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '17da9147c7cb'
down_revision: Union[str, None] = '5943ff1fb78d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add user_id to screener_presets (missed in the Wave-3 tenancy migration) + backfill owner."""
    op.add_column(
        "screener_presets",
        sa.Column("user_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True),
    )
    op.create_index("ix_screener_presets_user_id", "screener_presets", ["user_id"])
    conn = op.get_bind()
    row = conn.execute(sa.text("SELECT id FROM users WHERE is_superuser = 1 ORDER BY id LIMIT 1")).fetchone()
    if row is not None:
        conn.execute(
            sa.text("UPDATE screener_presets SET user_id = :oid WHERE user_id IS NULL"),
            {"oid": row[0]},
        )


def downgrade() -> None:
    op.drop_index("ix_screener_presets_user_id", table_name="screener_presets")
    op.drop_column("screener_presets", "user_id")
