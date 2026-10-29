"""Persist custom debate rounds in saved Analyze flows.

Revision ID: a4c8d2e6f901
Revises: f0a1b2c3d4e5
"""

from alembic import op
import sqlalchemy as sa

revision = "a4c8d2e6f901"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("analyze_flows", sa.Column(
        "debate_rounds", sa.Integer(), nullable=False, server_default="1"))


def downgrade():
    op.drop_column("analyze_flows", "debate_rounds")
