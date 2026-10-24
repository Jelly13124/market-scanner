"""add_analyze_flows

Phase 5D: saved AnalyzeFlow templates for the Analyze panel's React Flow
canvas. Stores included sections + persona overrides; not FK'd to
ResearchReport (templates are reusable across runs/tickers).

Revision ID: c5d8a1f3e7b2
Revises: e7b9f3c5d1a8
Create Date: 2026-05-24 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c5d8a1f3e7b2"
down_revision: Union[str, None] = "e7b9f3c5d1a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create analyze_flows table."""
    op.create_table(
        "analyze_flows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("included_sections", sa.JSON(), nullable=False),
        sa.Column("persona_overrides", sa.JSON(), nullable=True),
        sa.Column("use_personas", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_analyze_flows_name"),
    )
    op.create_index(
        op.f("ix_analyze_flows_id"), "analyze_flows", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_analyze_flows_name"), "analyze_flows", ["name"], unique=False
    )


def downgrade() -> None:
    """Drop analyze_flows table."""
    op.drop_index(op.f("ix_analyze_flows_name"), table_name="analyze_flows")
    op.drop_index(op.f("ix_analyze_flows_id"), table_name="analyze_flows")
    op.drop_table("analyze_flows")
