"""scanner_config_email_flags

Two sibling boolean flags on ``ScannerConfig`` that gate NEW email delivery
after a scan completes (the delivery wiring itself is a later task):

  * ``email_watchlist`` (bool, default False) — email the watchlist ticker
    list to the user's verified report recipients after a scan.
  * ``email_reports`` (bool, default False) — also email the auto-SOP
    reports to those recipients.

Revision ID: b4c1e9f2a7d6
Revises: a3f1c7e9b2d5
Create Date: 2026-06-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4c1e9f2a7d6"
down_revision: Union[str, None] = "a3f1c7e9b2d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add email_watchlist + email_reports to scanner_configs.

    SQLite-safe via batch_alter_table (matches the auto_sop pattern). Server
    defaults backfill existing rows with the disabled (false) state so no
    surprise emails go out for already-configured scans.
    """
    with op.batch_alter_table("scanner_configs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "email_watchlist",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "email_reports",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    """Drop the two columns (reverse order)."""
    with op.batch_alter_table("scanner_configs") as batch_op:
        batch_op.drop_column("email_reports")
        batch_op.drop_column("email_watchlist")
