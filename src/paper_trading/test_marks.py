"""Offline tests for the daily mark-to-market (Task 5).

Fully offline: a scratch in-memory SQLite engine + ``Session`` (same setup as
``test_engine.py``) and a trivial in-process ``price_fn`` stub. No network, no
LLM, no broker object — these functions reconstruct equity purely from the DB,
which is the whole point of the architecture they back.

The cases pin the load-bearing mark contract: DB-derived cash that ignores
rejected orders, equity = cash + Σ(open shares × price), a missing price that
excludes a name without raising, the idempotent ``(sleeve, date)`` upsert, the
graceful unknown-sleeve return, and the ``mark_all`` fan-out.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.backend.database.connection import Base
from app.backend.database.models import (
    PaperEquityMark,
    PaperOrder,
    PaperPosition,
    PaperSleeve,
)
from src.paper_trading.marks import derive_cash, mark_all, mark_sleeve

MARK_DATE = "2026-06-08"


# -- fixtures / helpers -------------------------------------------------------


@pytest.fixture()
def session():
    """Fresh in-memory SQLite session with the paper-trading tables created."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess
    engine.dispose()


def _price(prices: dict[str, float]):
    """Build a ``price_fn`` stub returning marks from ``prices`` (None if absent)."""

    def price_fn(ticker: str):
        return prices.get(ticker)

    return price_fn


def _make_sleeve(session, name: str, starting_cash: float) -> PaperSleeve:
    sleeve = PaperSleeve(name=name, starting_cash=starting_cash)
    session.add(sleeve)
    session.flush()  # assign sleeve.id
    return sleeve


def _add_order(session, sleeve_id, ticker, side, qty, price, status, week_key="2026-W24"):
    session.add(
        PaperOrder(
            sleeve_id=sleeve_id,
            ticker=ticker,
            side=side,
            qty=qty,
            price=price,
            status=status,
            week_key=week_key,
        )
    )


def _add_open_position(session, sleeve_id, ticker, shares, entry_price):
    session.add(
        PaperPosition(
            sleeve_id=sleeve_id,
            ticker=ticker,
            shares=shares,
            entry_date=MARK_DATE,
            entry_price=entry_price,
            status="open",
        )
    )


# -- 1. derive_cash: filled buys/sells move cash, rejects don't ---------------


def test_derive_cash_sums_filled_orders_only(session) -> None:
    sleeve = _make_sleeve(session, "scanner_only", 100_000.0)
    # 2 buys, 1 sell — all filled — plus one rejected buy that must be ignored.
    _add_order(session, sleeve.id, "AAA", "buy", 50, 100.0, "filled")  # -5_000
    _add_order(session, sleeve.id, "BBB", "buy", 25, 200.0, "filled")  # -5_000
    _add_order(session, sleeve.id, "AAA", "sell", 10, 120.0, "filled")  # +1_200
    _add_order(session, sleeve.id, "CCC", "buy", 1_000, 999.0, "rejected")  # ignored
    session.commit()

    cash = derive_cash(sleeve.id, session, starting_cash=sleeve.starting_cash)
    # 100_000 - 5_000 - 5_000 + 1_200 = 91_200.
    assert cash == pytest.approx(91_200.0)


def test_derive_cash_rejected_order_does_not_affect_cash(session) -> None:
    sleeve = _make_sleeve(session, "scanner_only", 100_000.0)
    _add_order(session, sleeve.id, "ZZZ", "buy", 5, 1_000.0, "rejected")
    session.commit()

    cash = derive_cash(sleeve.id, session, starting_cash=sleeve.starting_cash)
    assert cash == pytest.approx(100_000.0)


# -- 2. mark_sleeve happy path ------------------------------------------------


def test_mark_sleeve_happy_path(session) -> None:
    sleeve = _make_sleeve(session, "scanner_only", 100_000.0)
    # Filled buys → cash drops; positions held against current prices.
    _add_order(session, sleeve.id, "AAA", "buy", 50, 100.0, "filled")  # -5_000
    _add_order(session, sleeve.id, "BBB", "buy", 25, 200.0, "filled")  # -5_000
    _add_open_position(session, sleeve.id, "AAA", 50.0, 100.0)
    _add_open_position(session, sleeve.id, "BBB", 25.0, 200.0)
    session.commit()

    prices = {"AAA": 110.0, "BBB": 190.0}
    equity = mark_sleeve("scanner_only", MARK_DATE, session=session, price_fn=_price(prices))

    cash = derive_cash(sleeve.id, session, starting_cash=sleeve.starting_cash)
    expected = cash + 50.0 * 110.0 + 25.0 * 190.0
    assert equity == pytest.approx(expected)
    # cash = 90_000; positions = 5_500 + 4_750 = 10_250 → equity = 100_250.
    assert equity == pytest.approx(100_250.0)

    # Exactly one equity-mark row for this sleeve+date.
    marks = session.query(PaperEquityMark).filter_by(sleeve_id=sleeve.id).all()
    assert len(marks) == 1
    assert marks[0].date == MARK_DATE
    assert marks[0].equity == pytest.approx(expected)


# -- 3. missing price excludes the name, no raise -----------------------------


def test_mark_sleeve_missing_price_skips_name(session) -> None:
    sleeve = _make_sleeve(session, "scanner_only", 100_000.0)
    _add_order(session, sleeve.id, "AAA", "buy", 50, 100.0, "filled")  # -5_000
    _add_order(session, sleeve.id, "BBB", "buy", 25, 200.0, "filled")  # -5_000
    _add_open_position(session, sleeve.id, "AAA", 50.0, 100.0)
    _add_open_position(session, sleeve.id, "BBB", 25.0, 200.0)
    session.commit()

    # Price for BBB is unavailable → BBB excluded from equity, no raise.
    prices = {"AAA": 110.0}
    equity = mark_sleeve("scanner_only", MARK_DATE, session=session, price_fn=_price(prices))

    cash = derive_cash(sleeve.id, session, starting_cash=sleeve.starting_cash)
    # Only AAA counted: cash 90_000 + 50*110 = 95_500. BBB omitted.
    assert equity == pytest.approx(cash + 50.0 * 110.0)
    assert equity == pytest.approx(95_500.0)


# -- 4. upsert: same (sleeve, date) twice → one row, updated value ------------


def test_mark_sleeve_upsert_overwrites_same_day(session) -> None:
    sleeve = _make_sleeve(session, "scanner_only", 100_000.0)
    _add_order(session, sleeve.id, "AAA", "buy", 50, 100.0, "filled")  # -5_000
    _add_open_position(session, sleeve.id, "AAA", 50.0, 100.0)
    session.commit()

    first = mark_sleeve("scanner_only", MARK_DATE, session=session, price_fn=_price({"AAA": 100.0}))
    # cash 95_000 + 50*100 = 100_000.
    assert first == pytest.approx(100_000.0)

    # Re-mark the same day at a different price → row updated, not duplicated.
    second = mark_sleeve("scanner_only", MARK_DATE, session=session, price_fn=_price({"AAA": 120.0}))
    # cash 95_000 + 50*120 = 101_000.
    assert second == pytest.approx(101_000.0)

    marks = session.query(PaperEquityMark).filter_by(sleeve_id=sleeve.id, date=MARK_DATE).all()
    assert len(marks) == 1
    assert marks[0].equity == pytest.approx(101_000.0)


# -- 5. unknown sleeve_name → None, no raise, no row --------------------------


def test_mark_sleeve_unknown_sleeve_returns_none(session) -> None:
    result = mark_sleeve("does_not_exist", MARK_DATE, session=session, price_fn=_price({}))
    assert result is None
    assert session.query(PaperEquityMark).count() == 0


# -- 6. mark_all marks every seeded sleeve ------------------------------------


def test_mark_all_marks_every_sleeve(session) -> None:
    s1 = _make_sleeve(session, "scanner_agent", 100_000.0)
    s2 = _make_sleeve(session, "scanner_only", 100_000.0)
    s3 = _make_sleeve(session, "spy_benchmark", 100_000.0)

    # s1: holds AAA; s2: holds BBB; s3: no positions (pure cash).
    _add_order(session, s1.id, "AAA", "buy", 10, 100.0, "filled")  # -1_000
    _add_open_position(session, s1.id, "AAA", 10.0, 100.0)
    _add_order(session, s2.id, "BBB", "buy", 5, 200.0, "filled")  # -1_000
    _add_open_position(session, s2.id, "BBB", 5.0, 200.0)
    session.commit()

    prices = {"AAA": 110.0, "BBB": 220.0}
    results = mark_all(MARK_DATE, session=session, price_fn=_price(prices))

    assert set(results.keys()) == {"scanner_agent", "scanner_only", "spy_benchmark"}
    # s1: 99_000 + 10*110 = 100_100.
    assert results["scanner_agent"] == pytest.approx(100_100.0)
    # s2: 99_000 + 5*220 = 100_100.
    assert results["scanner_only"] == pytest.approx(100_100.0)
    # s3: pure cash, no orders → 100_000.
    assert results["spy_benchmark"] == pytest.approx(100_000.0)

    # One mark row per sleeve.
    assert session.query(PaperEquityMark).count() == 3
