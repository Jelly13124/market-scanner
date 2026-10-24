"""user_id not null on owned tables

Revision ID: 58ae3db295eb
Revises: 75ec58cc6c14
Create Date: 2026-05-29 23:06:12.431215

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '58ae3db295eb'
down_revision: Union[str, None] = '75ec58cc6c14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OWNED = ["api_keys", "scanner_configs", "pipeline_runs", "pipeline_schedule",
          "notification_subscriptions", "research_reports", "user_watchlists",
          "analyze_flows", "strategies", "lab_chat_messages", "backtests", "screener_presets"]
_UID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    """Enforce user_id NOT NULL on every owned table (every writer now sets it)."""
    conn = op.get_bind()
    # defensive: backfill any stray NULLs to the seed owner before NOT NULL
    row = conn.execute(sa.text("SELECT id FROM users WHERE is_superuser=1 ORDER BY id LIMIT 1")).fetchone()
    if row is not None:
        for t in _OWNED:
            conn.execute(sa.text(f"UPDATE {t} SET user_id = :o WHERE user_id IS NULL"), {"o": row[0]})
    for t in _OWNED:
        with op.batch_alter_table(t) as b:
            b.alter_column("user_id", existing_type=_UID, nullable=False)


def downgrade() -> None:
    for t in _OWNED:
        with op.batch_alter_table(t) as b:
            b.alter_column("user_id", existing_type=_UID, nullable=True)
