"""add_pipeline_tables

Creates ``pipeline_runs`` and ``pipeline_schedule`` for the scanner→agent
bridge (M10). Seeds a single ``pipeline_schedule`` row with the cron job
disabled by default — daily LLM cost is non-trivial; users opt in via UI.

Revision ID: b3d8f1a2c9e4
Revises: a2c4e6b8d0f3
Create Date: 2026-05-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3d8f1a2c9e4"
down_revision: Union[str, None] = "a2c4e6b8d0f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scan_date", sa.String(length=10), nullable=False),
        sa.Column("template", sa.String(length=50), nullable=False),
        sa.Column("selected_analysts", sa.JSON(), nullable=False),
        sa.Column("top_n", sa.Integer(), nullable=False),
        sa.Column("universe", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="PENDING"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("watchlist_json", sa.JSON(), nullable=True),
        sa.Column("agent_decisions_json", sa.JSON(), nullable=True),
        sa.Column("analyst_signals_json", sa.JSON(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pipeline_runs_id"), "pipeline_runs", ["id"], unique=False)
    op.create_index(op.f("ix_pipeline_runs_scan_date"), "pipeline_runs", ["scan_date"], unique=False)
    op.create_index(op.f("ix_pipeline_runs_status"), "pipeline_runs", ["status"], unique=False)

    op.create_table(
        "pipeline_schedule",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("top_n", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("template", sa.String(length=50), nullable=False, server_default="balanced"),
        sa.Column("universe", sa.String(length=50), nullable=False, server_default="nasdaq100"),
        sa.Column("model_name", sa.String(length=100), nullable=False, server_default="gpt-4.1"),
        sa.Column("model_provider", sa.String(length=50), nullable=False, server_default="OpenAI"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Seed the singleton row. Daily cron stays OFF until the user opts in
    # (mitigates the "LLM cost surprise" risk in the implementation plan).
    op.execute(
        "INSERT INTO pipeline_schedule "
        "(id, enabled, top_n, template, universe, model_name, model_provider) "
        "VALUES (1, 0, 5, 'balanced', 'nasdaq100', 'gpt-4.1', 'OpenAI')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("pipeline_schedule")
    op.drop_index(op.f("ix_pipeline_runs_status"), table_name="pipeline_runs")
    op.drop_index(op.f("ix_pipeline_runs_scan_date"), table_name="pipeline_runs")
    op.drop_index(op.f("ix_pipeline_runs_id"), table_name="pipeline_runs")
    op.drop_table("pipeline_runs")
