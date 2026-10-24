"""Offline tests for the paper-trading persistence layer (Task 2).

Two independent checks, both fully offline against scratch SQLite:

1. ORM round-trip — ``Base.metadata.create_all`` on an in-memory engine, then
   insert + read back one row of each of the four models, asserting the FKs
   link sleeve -> position/order/equity and that the unique (sleeve_id, date)
   on ``paper_equity_marks`` is enforced.

2. Migration symmetry — bind the migration's ``upgrade()`` / ``downgrade()`` to
   a fresh scratch SQLite connection via an Alembic Operations context, assert
   the four tables appear after upgrade and are gone after downgrade.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.backend.database.connection import Base
from app.backend.database.models import (
    PaperEquityMark,
    PaperOrder,
    PaperPosition,
    PaperSleeve,
)

PAPER_TABLES = {
    "paper_sleeves",
    "paper_positions",
    "paper_orders",
    "paper_equity_marks",
}


# --------------------------------------------------------------------------- #
# Part 1: ORM round-trip
# --------------------------------------------------------------------------- #
@pytest.fixture()
def sqlite_engine():
    """Fresh in-memory SQLite engine with FK enforcement turned on.

    SQLite ignores foreign keys unless ``PRAGMA foreign_keys=ON`` is set per
    connection, so we enable it to actually exercise the (sleeve_id) links.
    """
    engine = create_engine("sqlite://")

    @sa.event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def test_orm_round_trip_links_fks_across_all_four_models(sqlite_engine) -> None:
    with Session(sqlite_engine) as session:
        sleeve = PaperSleeve(name="scanner_agent", starting_cash=100_000.0)
        session.add(sleeve)
        session.flush()  # assigns sleeve.id

        session.add_all(
            [
                PaperPosition(
                    sleeve_id=sleeve.id,
                    ticker="AAPL",
                    shares=10.0,
                    entry_date="2026-06-08",
                    entry_price=100.0,
                    status="open",
                ),
                PaperOrder(
                    sleeve_id=sleeve.id,
                    ticker="AAPL",
                    side="buy",
                    qty=10.0,
                    price=100.0,
                    status="filled",
                    week_key="2026-W24",
                ),
                PaperEquityMark(
                    sleeve_id=sleeve.id,
                    date="2026-06-08",
                    equity=100_000.0,
                ),
            ]
        )
        session.commit()

    # Read back on a fresh session and assert every row links to the sleeve.
    with Session(sqlite_engine) as session:
        sleeve = session.query(PaperSleeve).filter_by(name="scanner_agent").one()
        assert sleeve.id is not None
        assert sleeve.starting_cash == 100_000.0
        assert sleeve.created_at is not None  # server_default fired

        position = session.query(PaperPosition).one()
        assert position.sleeve_id == sleeve.id
        assert position.ticker == "AAPL"
        assert position.shares == 10.0
        assert position.entry_price == 100.0
        assert position.exit_date is None  # nullable, still open
        assert position.exit_price is None
        assert position.status == "open"

        order = session.query(PaperOrder).one()
        assert order.sleeve_id == sleeve.id
        assert order.side == "buy"
        assert order.qty == 10.0
        assert order.status == "filled"
        assert order.week_key == "2026-W24"
        assert order.created_at is not None

        mark = session.query(PaperEquityMark).one()
        assert mark.sleeve_id == sleeve.id
        assert mark.date == "2026-06-08"
        assert mark.equity == 100_000.0


def test_equity_mark_unique_sleeve_date_is_enforced(sqlite_engine) -> None:
    with Session(sqlite_engine) as session:
        sleeve = PaperSleeve(name="spy_benchmark", starting_cash=100_000.0)
        session.add(sleeve)
        session.flush()
        session.add(
            PaperEquityMark(sleeve_id=sleeve.id, date="2026-06-08", equity=1.0)
        )
        session.commit()
        sleeve_id = sleeve.id

    # A second mark for the same (sleeve_id, date) must violate the unique key.
    with Session(sqlite_engine) as session:
        session.add(
            PaperEquityMark(sleeve_id=sleeve_id, date="2026-06-08", equity=2.0)
        )
        with pytest.raises(sa.exc.IntegrityError):
            session.commit()


def test_position_fk_requires_existing_sleeve(sqlite_engine) -> None:
    # With PRAGMA foreign_keys=ON, a dangling sleeve_id must be rejected.
    with Session(sqlite_engine) as session:
        session.add(
            PaperPosition(
                sleeve_id=999,  # no such sleeve
                ticker="AAPL",
                shares=1.0,
                entry_date="2026-06-08",
                entry_price=1.0,
                status="open",
            )
        )
        with pytest.raises(sa.exc.IntegrityError):
            session.commit()


# --------------------------------------------------------------------------- #
# Part 2: migration upgrade/downgrade symmetry
# --------------------------------------------------------------------------- #
def _load_migration_module():
    """Import the migration by file path (module name starts with a digit)."""
    path = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "backend"
        / "alembic"
        / "versions"
        / "f0a1b2c3d4e5_add_paper_trading_tables.py"
    )
    spec = importlib.util.spec_from_file_location("paper_trading_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_revision_points_at_current_head() -> None:
    module = _load_migration_module()
    assert module.revision == "f0a1b2c3d4e5"
    # Down-revision must be the verified alembic head at authoring time.
    assert module.down_revision == "c5d2f0a1e9b7"


def test_migration_upgrade_then_downgrade_is_symmetric() -> None:
    module = _load_migration_module()
    engine = create_engine("sqlite://")
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                module.upgrade()

            tables_after_upgrade = set(inspect(conn).get_table_names())
            assert PAPER_TABLES.issubset(tables_after_upgrade), (
                f"missing tables after upgrade: {PAPER_TABLES - tables_after_upgrade}"
            )

            with Operations.context(ctx):
                module.downgrade()

            tables_after_downgrade = set(inspect(conn).get_table_names())
            assert not (PAPER_TABLES & tables_after_downgrade), (
                f"tables left after downgrade: {PAPER_TABLES & tables_after_downgrade}"
            )
    finally:
        engine.dispose()
