"""Persist the Analyze configuration snapshot for scheduled reports."""
from alembic import op
import sqlalchemy as sa

revision = 'd7e3f901b625'
down_revision = 'c6d9e2f4a810'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('report_schedules', sa.Column('analysis_config', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('report_schedules', 'analysis_config')
