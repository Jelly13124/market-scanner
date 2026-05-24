"""add_user_watchlists

Phase 5B: user-curated watchlist table for the left-sidebar feature.
Separate from ``watchlist_entries`` (scanner output) — this is the
user's personal "stocks I'm tracking" list.

Revision ID: e7b9f3c5d1a8
Revises: d9f1c5b8e2a6
Create Date: 2026-05-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7b9f3c5d1a8"
down_revision: Union[str, None] = "d9f1c5b8e2a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create user_watchlists table."""
    op.create_table(
        "user_watchlists",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("tickers", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_user_watchlists_name"),
    )
    op.create_index(
        op.f("ix_user_watchlists_id"), "user_watchlists", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_user_watchlists_name"), "user_watchlists", ["name"], unique=False
    )


def downgrade() -> None:
    """Drop user_watchlists table."""
    op.drop_index(op.f("ix_user_watchlists_name"), table_name="user_watchlists")
    op.drop_index(op.f("ix_user_watchlists_id"), table_name="user_watchlists")
    op.drop_table("user_watchlists")
