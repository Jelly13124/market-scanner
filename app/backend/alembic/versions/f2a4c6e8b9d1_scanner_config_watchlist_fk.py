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
    """Add user_watchlist_id FK column + index to scanner_configs."""
    op.add_column(
        "scanner_configs",
        sa.Column("user_watchlist_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_scanner_configs_user_watchlist_id",
        "scanner_configs",
        ["user_watchlist_id"],
    )
    op.create_foreign_key(
        "fk_scanner_configs_user_watchlist",
        "scanner_configs",
        "user_watchlists",
        ["user_watchlist_id"],
        ["id"],
    )


def downgrade() -> None:
    """Drop FK constraint, index, and column (reverse order)."""
    op.drop_constraint(
        "fk_scanner_configs_user_watchlist",
        "scanner_configs",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_scanner_configs_user_watchlist_id",
        table_name="scanner_configs",
    )
    op.drop_column("scanner_configs", "user_watchlist_id")
