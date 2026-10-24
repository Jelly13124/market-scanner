"""add timezone to users

Per-user IANA timezone. Adds ``users.timezone`` (str(64), NOT NULL,
server_default "America/New_York") so existing rows backfill to ET. The
scheduler reads this (separate task) to interpret each user's report crons in
their own zone. Additive + SQLite/Postgres safe via batch_alter_table.

Revision ID: a3f1c7e9b2d5
Revises: dfdecadcbff0
Create Date: 2026-06-02 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a3f1c7e9b2d5"
down_revision: Union[str, None] = "dfdecadcbff0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add users.timezone (NOT NULL, server_default America/New_York)."""
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "timezone",
                sa.String(64),
                nullable=False,
                server_default="America/New_York",
            )
        )


def downgrade() -> None:
    """Drop users.timezone."""
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("timezone")
