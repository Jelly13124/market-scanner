"""drop_hedge_fund_flow_tables

Destructive cleanup migration: removes the three tables that backed the
deleted React Flow UI tab (hedge_fund_flow_run_cycles,
hedge_fund_flow_runs, hedge_fund_flows). Run order is FK-aware: cycles
first (FK to runs), then runs (FK to flows), then flows.

``downgrade()`` intentionally raises — the source-of-truth ORM classes
are gone, so re-creating these tables would require copying the
original column definitions back here. If you actually need to roll
this back, restore from git history (commit ``5274886e5bee`` ..
``3f9a6b7c8d2e``).

Revision ID: a1b2c3d4e5f6
Revises: b8d2f9a4e6c1
Create Date: 2026-05-24 22:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "b8d2f9a4e6c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the three HedgeFundFlow tables in FK-aware order.

    ``DROP TABLE IF EXISTS`` keeps the migration idempotent for fresh
    databases that never had these tables (e.g. a clean checkout that
    ran ``Base.metadata.create_all`` after the ORM classes were already
    removed).
    """
    op.execute("DROP TABLE IF EXISTS hedge_fund_flow_run_cycles")
    op.execute("DROP TABLE IF EXISTS hedge_fund_flow_runs")
    op.execute("DROP TABLE IF EXISTS hedge_fund_flows")


def downgrade() -> None:
    """Not reversible — see module docstring."""
    raise NotImplementedError(
        "destructive migration; restore from git history if needed",
    )
