"""add_analyze_columns

Phase 4: additive columns on research_reports for the SOP-driven Analyze
pipeline. analyze_request_json serializes the full AnalyzeRequest
(objective, budget, cost_basis, risk_tolerance, included_sections,
use_personas). sections_json stores dict[section_name -> section_structured]
for downstream structured access without re-parsing markdown.

Both columns are nullable so Phase 3 rows (created before this migration)
remain valid without backfill.

Revision ID: d9f1c5b8e2a6
Revises: c8e7a1d2f3b4
Create Date: 2026-05-22 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d9f1c5b8e2a6"
down_revision: Union[str, None] = "c8e7a1d2f3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add analyze_request_json + sections_json columns to research_reports."""
    op.add_column(
        "research_reports",
        sa.Column("analyze_request_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "research_reports",
        sa.Column("sections_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """Drop the Phase 4 columns."""
    op.drop_column("research_reports", "sections_json")
    op.drop_column("research_reports", "analyze_request_json")
