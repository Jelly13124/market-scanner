"""add_lab_tables

Phase 6: strategies + lab_chat_messages + backtests for the AI strategy
lab. Additive; no changes to Phase 1-5 tables.

Revision ID: c3e7f9d2b8a4
Revises: a1b2c3d4e5f6
Create Date: 2026-05-25 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3e7f9d2b8a4"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "strategies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                   server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("spec_json", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_strategies_id"), "strategies", ["id"], unique=False)
    op.create_index(op.f("ix_strategies_name"), "strategies", ["name"], unique=True)

    op.create_table(
        "lab_chat_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                   server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("spec_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("spec_patch_json", sa.JSON(), nullable=True),
        sa.Column("patch_accepted", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_lab_chat_messages_id"), "lab_chat_messages", ["id"], unique=False)
    op.create_index(op.f("ix_lab_chat_messages_strategy_id"), "lab_chat_messages",
                     ["strategy_id"], unique=False)

    op.create_table(
        "backtests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                   server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("spec_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("start_date", sa.String(length=10), nullable=False),
        sa.Column("end_date", sa.String(length=10), nullable=False),
        sa.Column("midpoint_date", sa.String(length=10), nullable=False),
        sa.Column("universe_size", sa.Integer(), nullable=False),
        # IS
        sa.Column("is_total_return", sa.Float(), nullable=True),
        sa.Column("is_cagr", sa.Float(), nullable=True),
        sa.Column("is_sharpe", sa.Float(), nullable=True),
        sa.Column("is_sortino", sa.Float(), nullable=True),
        sa.Column("is_max_drawdown", sa.Float(), nullable=True),
        sa.Column("is_calmar", sa.Float(), nullable=True),
        sa.Column("is_win_rate", sa.Float(), nullable=True),
        sa.Column("is_profit_factor", sa.Float(), nullable=True),
        sa.Column("is_n_trades", sa.Integer(), nullable=True),
        sa.Column("is_avg_holding_days", sa.Float(), nullable=True),
        # OOS
        sa.Column("oos_total_return", sa.Float(), nullable=True),
        sa.Column("oos_cagr", sa.Float(), nullable=True),
        sa.Column("oos_sharpe", sa.Float(), nullable=True),
        sa.Column("oos_sortino", sa.Float(), nullable=True),
        sa.Column("oos_max_drawdown", sa.Float(), nullable=True),
        sa.Column("oos_calmar", sa.Float(), nullable=True),
        sa.Column("oos_win_rate", sa.Float(), nullable=True),
        sa.Column("oos_profit_factor", sa.Float(), nullable=True),
        sa.Column("oos_n_trades", sa.Integer(), nullable=True),
        sa.Column("oos_avg_holding_days", sa.Float(), nullable=True),
        # Verdict + payloads
        sa.Column("degradation_ratio", sa.Float(), nullable=True),
        sa.Column("benchmark_cagr", sa.Float(), nullable=True),
        sa.Column("verdict_label", sa.String(length=30), nullable=False),
        sa.Column("verdict_text", sa.Text(), nullable=False),
        sa.Column("trades_json", sa.JSON(), nullable=False),
        sa.Column("equity_curve_is", sa.JSON(), nullable=False),
        sa.Column("equity_curve_oos", sa.JSON(), nullable=False),
        sa.Column("benchmark_curve", sa.JSON(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_backtests_id"), "backtests", ["id"], unique=False)
    op.create_index(op.f("ix_backtests_strategy_id"), "backtests", ["strategy_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_backtests_strategy_id"), table_name="backtests")
    op.drop_index(op.f("ix_backtests_id"), table_name="backtests")
    op.drop_table("backtests")
    op.drop_index(op.f("ix_lab_chat_messages_strategy_id"), table_name="lab_chat_messages")
    op.drop_index(op.f("ix_lab_chat_messages_id"), table_name="lab_chat_messages")
    op.drop_table("lab_chat_messages")
    op.drop_index(op.f("ix_strategies_name"), table_name="strategies")
    op.drop_index(op.f("ix_strategies_id"), table_name="strategies")
    op.drop_table("strategies")
