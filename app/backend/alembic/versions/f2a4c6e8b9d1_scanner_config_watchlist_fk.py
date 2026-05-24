"""scanner_config_watchlist_fk

Phase 5C: ``ScannerConfig`` gets a nullable ``user_watchlist_id`` FK so a
scan can target a user-curated watchlist as its universe. Empty/null for
existing rows (which keep their original ``universe_kind`` resolution).

Revision ID: f2a4c6e8b9d1
Revises: c5d8a1f3e7b2
Create Date: 2026-05-24 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2a4c6e8b9d1"
down_revision: Union[str, None] = "c5d8a1f3e7b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add user_watchlist_id FK column + index to scanner_configs.

    SQLite has no ALTER ... ADD FOREIGN KEY, so both the column and the FK
    constraint live inside a single batch_alter_table block (table
    copy-and-move). The accompanying index is created right after; both
    must succeed or the upgrade leaves residuals — bare SQLite has no
    DDL transactions.
    """
    with op.batch_alter_table("scanner_configs") as batch_op:
        batch_op.add_column(
            sa.Column("user_watchlist_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_scanner_configs_user_watchlist",
            "user_watchlists",
            ["user_watchlist_id"],
            ["id"],
        )
        batch_op.create_index(
            "ix_scanner_configs_user_watchlist_id",
            ["user_watchlist_id"],
        )


def downgrade() -> None:
    """Drop FK constraint, index, and column (reverse order)."""
    with op.batch_alter_table("scanner_configs") as batch_op:
        batch_op.drop_index("ix_scanner_configs_user_watchlist_id")
        batch_op.drop_constraint(
            "fk_scanner_configs_user_watchlist",
            type_="foreignkey",
        )
        batch_op.drop_column("user_watchlist_id")
