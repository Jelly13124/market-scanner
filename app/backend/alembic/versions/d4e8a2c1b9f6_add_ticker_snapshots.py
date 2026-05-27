"""add ticker_snapshots table

Revision ID: d4e8a2c1b9f6
Revises: c3e7f9d2b8a4
Create Date: 2026-05-27 22:00:00.000000

Adds the per-ticker per-day snapshot table backing the Screener tab.
Filtered queries (faceted chips) and nightly upserts both target this
single table. Unique (ticker, snapshot_date) makes upsert idempotent;
3 indices serve the common WHERE patterns (date alone, market+date,
sector+date).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e8a2c1b9f6"
down_revision: Union[str, None] = "c3e7f9d2b8a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ticker_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("market", sa.String(length=8), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("price", sa.Numeric(12, 4)),
        sa.Column("prev_close", sa.Numeric(12, 4)),
        sa.Column("change_pct", sa.Numeric(8, 4)),
        sa.Column("volume", sa.BigInteger()),
        sa.Column("avg_volume_10d", sa.BigInteger()),
        sa.Column("rel_volume", sa.Numeric(6, 3)),
        sa.Column("market_cap", sa.Numeric(20, 2)),
        sa.Column("pe_ttm", sa.Numeric(10, 3)),
        sa.Column("pe_forward", sa.Numeric(10, 3)),
        sa.Column("pb", sa.Numeric(10, 3)),
        sa.Column("ps", sa.Numeric(10, 3)),
        sa.Column("peg", sa.Numeric(10, 3)),
        sa.Column("eps_growth_yoy", sa.Numeric(10, 4)),
        sa.Column("revenue_growth_yoy", sa.Numeric(10, 4)),
        sa.Column("roe", sa.Numeric(10, 4)),
        sa.Column("profit_margin", sa.Numeric(10, 4)),
        sa.Column("dividend_yield_pct", sa.Numeric(8, 4)),
        sa.Column("beta", sa.Numeric(8, 3)),
        sa.Column("sector", sa.String(length=64)),
        sa.Column("industry", sa.String(length=128)),
        sa.Column("exchange", sa.String(length=16)),
        sa.Column("analyst_rating", sa.String(length=16)),
        sa.Column("analyst_count", sa.Integer()),
        sa.Column("target_mean_price", sa.Numeric(12, 4)),
        sa.Column("recent_earnings_date", sa.Date()),
        sa.Column("upcoming_earnings_date", sa.Date()),
        sa.Column("perf_1d", sa.Numeric(8, 4)),
        sa.Column("perf_5d", sa.Numeric(8, 4)),
        sa.Column("perf_1m", sa.Numeric(8, 4)),
        sa.Column("perf_3m", sa.Numeric(8, 4)),
        sa.Column("perf_ytd", sa.Numeric(8, 4)),
        sa.Column("perf_1y", sa.Numeric(8, 4)),
        sa.Column("data_source", sa.String(length=16)),
        sa.Column("last_updated", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("ticker", "snapshot_date", name="uq_snapshot_ticker_date"),
    )
    op.create_index("idx_snapshot_date", "ticker_snapshots", ["snapshot_date"])
    op.create_index("idx_snapshot_market_date", "ticker_snapshots",
                    ["market", "snapshot_date"])
    op.create_index("idx_snapshot_sector", "ticker_snapshots",
                    ["sector", "snapshot_date"])


def downgrade() -> None:
    op.drop_index("idx_snapshot_sector", table_name="ticker_snapshots")
    op.drop_index("idx_snapshot_market_date", table_name="ticker_snapshots")
    op.drop_index("idx_snapshot_date", table_name="ticker_snapshots")
    op.drop_table("ticker_snapshots")
