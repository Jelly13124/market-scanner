"""add screener_presets table

Revision ID: e1a7c2f4b9d0
Revises: d4e8a2c1b9f6
Create Date: 2026-05-29 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "e1a7c2f4b9d0"
down_revision: Union[str, None] = "d4e8a2c1b9f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "screener_presets",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
                  primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("market", sa.String(length=8)),
        sa.Column("filters_json", sa.JSON(), nullable=False),
        sa.Column("sort_by", sa.String(length=32), nullable=False,
                  server_default="market_cap"),
        sa.Column("sort_dir", sa.String(length=4), nullable=False,
                  server_default="desc"),
        sa.Column("schedule_enabled", sa.Boolean(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("notify_channels", sa.JSON()),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_match_count", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("screener_presets")
