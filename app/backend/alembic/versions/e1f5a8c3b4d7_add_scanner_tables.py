"""add_scanner_tables

Revision ID: e1f5a8c3b4d7
Revises: d5e78f9a1b2c
Create Date: 2026-05-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1f5a8c3b4d7'
down_revision: Union[str, None] = 'd5e78f9a1b2c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'scanner_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('universe_kind', sa.String(length=50), nullable=False),
        sa.Column('universe_tickers', sa.JSON(), nullable=True),
        sa.Column('cron_expr', sa.String(length=100), nullable=False, server_default='0 21 * * 1-5'),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('top_n', sa.Integer(), nullable=False, server_default='20'),
        sa.Column('weights', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_scanner_configs_id'), 'scanner_configs', ['id'], unique=False)

    op.create_table(
        'scan_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('config_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='PENDING'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('universe_size', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['config_id'], ['scanner_configs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_scan_runs_id'), 'scan_runs', ['id'], unique=False)
    op.create_index(op.f('ix_scan_runs_config_id'), 'scan_runs', ['config_id'], unique=False)

    op.create_table(
        'watchlist_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('scan_run_id', sa.Integer(), nullable=False),
        sa.Column('ticker', sa.String(length=20), nullable=False),
        sa.Column('composite_score', sa.Float(), nullable=False),
        sa.Column('direction', sa.String(length=20), nullable=False, server_default='neutral'),
        sa.Column('event_score', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('quant_score', sa.Float(), nullable=True),
        sa.Column('triggers', sa.JSON(), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['scan_run_id'], ['scan_runs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_watchlist_entries_id'), 'watchlist_entries', ['id'], unique=False)
    op.create_index(op.f('ix_watchlist_entries_scan_run_id'), 'watchlist_entries', ['scan_run_id'], unique=False)
    op.create_index(op.f('ix_watchlist_entries_ticker'), 'watchlist_entries', ['ticker'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_watchlist_entries_ticker'), table_name='watchlist_entries')
    op.drop_index(op.f('ix_watchlist_entries_scan_run_id'), table_name='watchlist_entries')
    op.drop_index(op.f('ix_watchlist_entries_id'), table_name='watchlist_entries')
    op.drop_table('watchlist_entries')

    op.drop_index(op.f('ix_scan_runs_config_id'), table_name='scan_runs')
    op.drop_index(op.f('ix_scan_runs_id'), table_name='scan_runs')
    op.drop_table('scan_runs')

    op.drop_index(op.f('ix_scanner_configs_id'), table_name='scanner_configs')
    op.drop_table('scanner_configs')
