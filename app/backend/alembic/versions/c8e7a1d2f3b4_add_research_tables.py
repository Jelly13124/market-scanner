"""add_research_tables

Creates research_reports + research_trade_plans for the per-stock
research pipeline (Phase 3). Additive only — no changes to existing
pipeline_runs / scanner_* / notification_* tables.

Revision ID: c8e7a1d2f3b4
Revises: b3d8f1a2c9e4
Create Date: 2026-05-22 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8e7a1d2f3b4"
down_revision: Union[str, None] = "b3d8f1a2c9e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — add the two research tables."""
    op.create_table(
        "research_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("scan_date", sa.String(length=10), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("report_markdown", sa.Text(), nullable=False),
        sa.Column("rendered_html", sa.Text(), nullable=False),
        sa.Column("use_personas", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("persona_assignments_json", sa.JSON(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_research_reports_id"), "research_reports", ["id"], unique=False)
    op.create_index(op.f("ix_research_reports_ticker"), "research_reports", ["ticker"], unique=False)
    op.create_index(op.f("ix_research_reports_scan_date"), "research_reports", ["scan_date"], unique=False)
    op.create_index("ix_research_reports_ticker_scan_date", "research_reports", ["ticker", "scan_date"], unique=False)

    op.create_table(
        "research_trade_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=True),
        sa.Column("target_price", sa.Float(), nullable=True),
        sa.Column("stop_price", sa.Float(), nullable=True),
        sa.Column("horizon_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sizing_pct", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("backtest_matches_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("backtest_win_rate", sa.Float(), nullable=True),
        sa.Column("backtest_avg_pnl_pct", sa.Float(), nullable=True),
        sa.Column("backtest_max_drawdown_pct", sa.Float(), nullable=True),
        sa.Column("backtest_avg_holding_days", sa.Float(), nullable=True),
        sa.Column("backtest_sample_quality", sa.String(length=20),
                  nullable=False, server_default="insufficient"),
        sa.Column("backtest_caveat", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["report_id"], ["research_reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_research_trade_plans_id"), "research_trade_plans", ["id"], unique=False)
    op.create_index(op.f("ix_research_trade_plans_report_id"), "research_trade_plans", ["report_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema — drop the two research tables.

    research_trade_plans first because it has FK into research_reports.
    """
    op.drop_index(op.f("ix_research_trade_plans_report_id"), table_name="research_trade_plans")
    op.drop_index(op.f("ix_research_trade_plans_id"), table_name="research_trade_plans")
    op.drop_table("research_trade_plans")

    op.drop_index("ix_research_reports_ticker_scan_date", table_name="research_reports")
    op.drop_index(op.f("ix_research_reports_scan_date"), table_name="research_reports")
    op.drop_index(op.f("ix_research_reports_ticker"), table_name="research_reports")
    op.drop_index(op.f("ix_research_reports_id"), table_name="research_reports")
    op.drop_table("research_reports")
