"""add user_id to owned tables + backfill owner

Revision ID: 359c3b216a47
Revises: 9bc3783803fc
Create Date: 2026-05-29 15:04:19.674251

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '359c3b216a47'
down_revision: Union[str, None] = '9bc3783803fc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tables that are owned by a user and receive user_id.
# NOTE: We use plain op.add_column + op.create_index rather than adding a FK
# constraint in the migration DDL because SQLite's ADD COLUMN cannot add FK
# constraints, and SQLite does not enforce FKs by default anyway.  The ORM
# model carries the ForeignKey("users.id") declaration for metadata introspection
# and future Postgres compatibility.
_OWNED_TABLES = [
    "api_keys",
    "scanner_configs",
    "pipeline_runs",
    "pipeline_schedule",
    "notification_subscriptions",
    "research_reports",
    "user_watchlists",
    "analyze_flows",
    "strategies",
    "lab_chat_messages",
    "backtests",
]


def upgrade() -> None:
    """Add user_id column + index to each owned table, then backfill with owner."""
    for t in _OWNED_TABLES:
        op.add_column(t, sa.Column("user_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True))
        op.create_index(f"ix_{t}_user_id", t, ["user_id"])

    # Seed or find the superuser owner, then backfill all existing rows.
    conn = op.get_bind()
    import os
    owner_email = os.getenv("SEED_OWNER_EMAIL", "owner@local")
    row = conn.execute(sa.text("SELECT id FROM users WHERE is_superuser = 1 ORDER BY id LIMIT 1")).fetchone()
    if row is None:
        conn.execute(
            sa.text(
                "INSERT INTO users (email, hashed_password, full_name, is_active, is_superuser, created_at) "
                "VALUES (:e, NULL, 'Owner', 1, 1, CURRENT_TIMESTAMP)"
            ),
            {"e": owner_email},
        )
        row = conn.execute(sa.text("SELECT id FROM users WHERE email = :e"), {"e": owner_email}).fetchone()
    owner_id = row[0]
    for t in _OWNED_TABLES:
        conn.execute(sa.text(f"UPDATE {t} SET user_id = :oid WHERE user_id IS NULL"), {"oid": owner_id})


def downgrade() -> None:
    """Remove user_id index and column from each owned table (leave seeded owner row)."""
    for t in reversed(_OWNED_TABLES):
        op.drop_index(f"ix_{t}_user_id", table_name=t)
        op.drop_column(t, "user_id")
