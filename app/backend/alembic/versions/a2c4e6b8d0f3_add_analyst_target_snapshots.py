"""add analyst_target_snapshots table

Revision ID: a2c4e6b8d0f3
Revises: f7b9c4e1d2a8
Create Date: 2026-05-15 22:00:00.000000

Adds per-ticker daily analyst-target snapshot table. Used by
TargetPriceChangeDetector to compute N-day target drift — the kind of
signal yfinance's static analyst_price_targets snapshot can't express
on its own.

Unique constraint on (ticker, asof_date) makes daily upserts idempotent:
the first scan of the day inserts, subsequent scans no-op (or refresh
target values if analysts updated mid-day).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a2c4e6b8d0f3'
down_revision: Union[str, None] = 'f7b9c4e1d2a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'analyst_target_snapshots',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('ticker', sa.String(length=20), nullable=False, index=True),
        sa.Column('asof_date', sa.String(length=10), nullable=False, index=True),
        sa.Column('target_mean', sa.Float(), nullable=True),
        sa.Column('target_median', sa.Float(), nullable=True),
        sa.Column('target_high', sa.Float(), nullable=True),
        sa.Column('target_low', sa.Float(), nullable=True),
        sa.Column('current_price', sa.Float(), nullable=True),
        sa.Column('n_analysts', sa.Integer(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.UniqueConstraint(
            'ticker', 'asof_date',
            name='uq_target_snapshot_ticker_date',
        ),
    )


def downgrade() -> None:
    op.drop_table('analyst_target_snapshots')
