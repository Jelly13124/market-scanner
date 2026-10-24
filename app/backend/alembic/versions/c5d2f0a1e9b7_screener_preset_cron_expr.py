"""screener_preset_cron_expr

Add a per-preset ``cron_expr`` to ``screener_presets`` so each saved Screener
filter can run on its own cadence (evaluated in the owner's timezone) instead of
the single global 22:05-ET preset cron. server_default "5 22 * * *" backfills
existing rows with that old global time, so behaviour is unchanged until a user
edits a preset's schedule.

Revision ID: c5d2f0a1e9b7
Revises: b4c1e9f2a7d6
Create Date: 2026-06-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c5d2f0a1e9b7"
down_revision: Union[str, None] = "b4c1e9f2a7d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add cron_expr to screener_presets (SQLite-safe via batch_alter_table).

    server_default "5 22 * * *" backfills existing rows with the prior global
    preset-cron time (22:05 daily) so already-enabled presets keep firing at the
    same time until their owner changes it.
    """
    with op.batch_alter_table("screener_presets") as batch_op:
        batch_op.add_column(
            sa.Column(
                "cron_expr",
                sa.String(length=100),
                nullable=False,
                server_default="5 22 * * *",
            )
        )


def downgrade() -> None:
    """Drop cron_expr."""
    with op.batch_alter_table("screener_presets") as batch_op:
        batch_op.drop_column("cron_expr")
