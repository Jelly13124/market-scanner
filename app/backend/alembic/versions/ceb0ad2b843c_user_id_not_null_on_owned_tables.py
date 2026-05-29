"""user_id not null on owned tables

Revision ID: ceb0ad2b843c
Revises: 359c3b216a47
Create Date: 2026-05-29 15:15:43.778462

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ceb0ad2b843c'
down_revision: Union[str, None] = '359c3b216a47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

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
_UID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    """Flip user_id to NOT NULL on all 11 user-owned tables."""
    for t in _OWNED_TABLES:
        with op.batch_alter_table(t) as batch_op:
            batch_op.alter_column("user_id", existing_type=_UID, nullable=False)


def downgrade() -> None:
    """Revert user_id back to nullable on all 11 user-owned tables."""
    for t in _OWNED_TABLES:
        with op.batch_alter_table(t) as batch_op:
            batch_op.alter_column("user_id", existing_type=_UID, nullable=True)
