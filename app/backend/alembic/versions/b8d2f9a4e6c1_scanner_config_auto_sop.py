"""scanner_config_auto_sop

Phase 5E: ``ScannerConfig`` gets two columns that drive an auto-SOP
follow-up after each scan completes:

  * ``auto_sop_top_n`` (int, default 0) — when > 0, run full SOP analysis
    on the top-N watchlist entries and bundle the reports into one
    email. 0 = disabled (legacy behavior).
  * ``auto_sop_use_personas`` (bool, default False) — whether the
    follow-up routes sections through the persona router.

Revision ID: b8d2f9a4e6c1
Revises: f2a4c6e8b9d1
Create Date: 2026-05-24 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8d2f9a4e6c1"
down_revision: Union[str, None] = "f2a4c6e8b9d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add auto_sop_top_n + auto_sop_use_personas to scanner_configs.

    SQLite-safe via batch_alter_table (matches the Phase 5C pattern). Server
    defaults backfill existing rows with the disabled (0 / false) state so
    the cron behavior is unchanged for already-configured scans.
    """
    with op.batch_alter_table("scanner_configs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "auto_sop_top_n",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "auto_sop_use_personas",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    """Drop the two columns (reverse order)."""
    with op.batch_alter_table("scanner_configs") as batch_op:
        batch_op.drop_column("auto_sop_use_personas")
        batch_op.drop_column("auto_sop_top_n")
