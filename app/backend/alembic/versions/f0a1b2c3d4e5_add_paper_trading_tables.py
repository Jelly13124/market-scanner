"""add_paper_trading_tables

Paper-trading forward-test harness (Task 2): four tables backing the three
side-by-side sleeves (scanner_agent / scanner_only / spy_benchmark) — the
sleeve book, its positions, an order audit log, and the daily equity marks.
Additive; touches no existing tables.

Revision ID: f0a1b2c3d4e5
Revises: c5d2f0a1e9b7
Create Date: 2026-06-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, None] = "c5d2f0a1e9b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "paper_sleeves",
        # Plain Integer PK — matches the ORM (Column(Integer, primary_key=True)).
        # SQLite autoincrements INTEGER PRIMARY KEY natively.
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("starting_cash", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_paper_sleeves_id"), "paper_sleeves", ["id"], unique=False)
    op.create_index(op.f("ix_paper_sleeves_name"), "paper_sleeves", ["name"], unique=True)

    op.create_table(
        "paper_positions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sleeve_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("shares", sa.Float(), nullable=False),
        sa.Column("entry_date", sa.String(length=10), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("exit_date", sa.String(length=10), nullable=True),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.ForeignKeyConstraint(["sleeve_id"], ["paper_sleeves.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_paper_positions_id"), "paper_positions", ["id"], unique=False)
    op.create_index(
        op.f("ix_paper_positions_sleeve_id"), "paper_positions", ["sleeve_id"], unique=False
    )
    op.create_index(
        op.f("ix_paper_positions_ticker"), "paper_positions", ["ticker"], unique=False
    )

    op.create_table(
        "paper_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sleeve_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("side", sa.String(length=10), nullable=False),
        sa.Column("qty", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("week_key", sa.String(length=10), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["sleeve_id"], ["paper_sleeves.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_paper_orders_id"), "paper_orders", ["id"], unique=False)
    op.create_index(
        op.f("ix_paper_orders_sleeve_id"), "paper_orders", ["sleeve_id"], unique=False
    )
    op.create_index(op.f("ix_paper_orders_ticker"), "paper_orders", ["ticker"], unique=False)
    op.create_index(
        op.f("ix_paper_orders_week_key"), "paper_orders", ["week_key"], unique=False
    )

    op.create_table(
        "paper_equity_marks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sleeve_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.String(length=10), nullable=False),
        sa.Column("equity", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["sleeve_id"], ["paper_sleeves.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sleeve_id", "date", name="uq_paper_equity_sleeve_date"),
    )
    op.create_index(
        op.f("ix_paper_equity_marks_id"), "paper_equity_marks", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_paper_equity_marks_sleeve_id"),
        "paper_equity_marks",
        ["sleeve_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_paper_equity_marks_date"), "paper_equity_marks", ["date"], unique=False
    )


def downgrade() -> None:
    # Reverse FK order: marks/orders/positions all reference sleeves, so drop
    # the children first and paper_sleeves last.
    op.drop_index(op.f("ix_paper_equity_marks_date"), table_name="paper_equity_marks")
    op.drop_index(op.f("ix_paper_equity_marks_sleeve_id"), table_name="paper_equity_marks")
    op.drop_index(op.f("ix_paper_equity_marks_id"), table_name="paper_equity_marks")
    op.drop_table("paper_equity_marks")

    op.drop_index(op.f("ix_paper_orders_week_key"), table_name="paper_orders")
    op.drop_index(op.f("ix_paper_orders_ticker"), table_name="paper_orders")
    op.drop_index(op.f("ix_paper_orders_sleeve_id"), table_name="paper_orders")
    op.drop_index(op.f("ix_paper_orders_id"), table_name="paper_orders")
    op.drop_table("paper_orders")

    op.drop_index(op.f("ix_paper_positions_ticker"), table_name="paper_positions")
    op.drop_index(op.f("ix_paper_positions_sleeve_id"), table_name="paper_positions")
    op.drop_index(op.f("ix_paper_positions_id"), table_name="paper_positions")
    op.drop_table("paper_positions")

    op.drop_index(op.f("ix_paper_sleeves_name"), table_name="paper_sleeves")
    op.drop_index(op.f("ix_paper_sleeves_id"), table_name="paper_sleeves")
    op.drop_table("paper_sleeves")
