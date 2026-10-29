"""Owner-isolated ordinary-user paper accounts.

Revision ID: c6d9e2f4a810
Revises: a4c8d2e6f901
"""
from alembic import op
import sqlalchemy as sa

revision = 'c6d9e2f4a810'
down_revision = 'a4c8d2e6f901'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('user_paper_accounts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), sa.ForeignKey('users.id'), nullable=False, unique=True),
        sa.Column('initial_cash', sa.Numeric(24, 6), nullable=False),
        sa.Column('cash', sa.Numeric(24, 6), nullable=False),
        sa.Column('realized_pnl', sa.Numeric(24, 6), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table('user_paper_positions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('user_paper_accounts.id'), nullable=False),
        sa.Column('ticker', sa.String(20), nullable=False),
        sa.Column('quantity', sa.Numeric(24, 6), nullable=False),
        sa.Column('cost_basis', sa.Numeric(24, 6), nullable=False),
        sa.Column('last_price', sa.Numeric(24, 6), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('account_id', 'ticker', name='uq_user_paper_position'))
    op.create_index('ix_user_paper_positions_account_id', 'user_paper_positions', ['account_id'])
    op.create_table('user_paper_trades',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('user_paper_accounts.id'), nullable=False),
        sa.Column('ticker', sa.String(20), nullable=False),
        sa.Column('side', sa.String(4), nullable=False),
        sa.Column('quantity', sa.Numeric(24, 6), nullable=False),
        sa.Column('price', sa.Numeric(24, 6), nullable=False),
        sa.Column('notional', sa.Numeric(24, 6), nullable=False),
        sa.Column('realized_pnl', sa.Numeric(24, 6), nullable=False),
        sa.Column('cash_after', sa.Numeric(24, 6), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index('ix_user_paper_trades_account_id', 'user_paper_trades', ['account_id'])


def downgrade():
    op.drop_table('user_paper_trades')
    op.drop_table('user_paper_positions')
    op.drop_table('user_paper_accounts')
