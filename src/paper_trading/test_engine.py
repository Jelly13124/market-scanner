"""Offline tests for the weekly rebalance engine (Task 4).

Fully offline: a deterministic ``FakeBroker``, a scratch in-memory SQLite
engine + ``Session``, and trivial in-process ``run_scan_fn`` / ``agent_fn``
stubs. No network, no LLM, no real orders.

The cases pin the load-bearing engine contract every later task depends on:
equal-weight entry with a share floor, idempotent re-runs, calendar-day
age-exit, the within-window keep, and the ``hold_days=None`` buy-and-hold path
used by ``spy_benchmark``.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.backend.database.connection import Base
from app.backend.database.models import PaperOrder, PaperPosition, PaperSleeve
from src.paper_trading.broker import FakeBroker
from src.paper_trading.engine import _calendar_days, run_week

SCAN_DATE = "2026-06-08"


# -- fixtures / stubs ---------------------------------------------------------


@pytest.fixture()
def session():
    """Fresh in-memory SQLite session with the paper-trading tables created."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess
    engine.dispose()


def _scan(tickers: list[str]):
    """Build a ``run_scan_fn`` stub returning ``tickers`` capped at ``top_n``."""

    def run_scan_fn(scan_date: str, top_n: int) -> list[str]:
        return list(tickers)[:top_n]

    return run_scan_fn


def _agent(decisions: dict[str, dict]):
    """Build an ``agent_fn`` stub returning a fixed decisions dict."""

    def agent_fn(tickers: list[str], scan_date: str) -> dict[str, dict]:
        return {t: decisions[t] for t in tickers if t in decisions}

    return agent_fn


def _days_before(scan_date: str, n: int) -> str:
    """ISO date ``n`` calendar days before ``scan_date``."""
    return (date.fromisoformat(scan_date) - timedelta(days=n)).isoformat()


# -- _calendar_days helper ----------------------------------------------------


def test_calendar_days_counts_calendar_days() -> None:
    assert _calendar_days("2026-06-01", "2026-07-01") == 30
    assert _calendar_days("2026-06-08", "2026-06-08") == 0
    # Direction matters: earlier second arg is negative.
    assert _calendar_days("2026-06-08", "2026-06-01") == -7


# -- 1. first run enters targets equal-weight ---------------------------------


def test_first_run_enters_targets_equal_weight(session) -> None:
    prices = {"AAA": 100.0, "BBB": 200.0}
    broker = FakeBroker(starting_cash=10_000.0, prices=prices)

    summary = run_week(
        sleeve_name="scanner_only",
        scan_date=SCAN_DATE,
        week_key="2026-W24",
        broker=broker,
        session=session,
        run_scan_fn=_scan(["AAA", "BBB"]),
    )

    assert summary["already_ran"] is False
    assert sorted(summary["entered"]) == ["AAA", "BBB"]
    assert summary["exited"] == []
    assert summary["n_orders"] == 2

    # 10_000 / 2 = 5_000 each → 50 AAA @100, 25 BBB @200.
    positions = session.query(PaperPosition).filter_by(status="open").order_by(PaperPosition.ticker).all()
    assert [(p.ticker, p.shares) for p in positions] == [("AAA", 50.0), ("BBB", 25.0)]
    assert all(p.entry_date == SCAN_DATE for p in positions)
    assert positions[0].entry_price == 100.0
    assert positions[1].entry_price == 200.0

    orders = session.query(PaperOrder).all()
    assert len(orders) == 2
    assert all(o.side == "buy" and o.status == "filled" for o in orders)
    assert all(o.week_key == "2026-W24" for o in orders)

    # Cash fully deployed: 10_000 - 50*100 - 25*200 = 0.
    assert summary["cash_after"] == pytest.approx(0.0)
    assert broker.get_account()["cash"] == pytest.approx(0.0)


# -- 2. idempotent re-run -----------------------------------------------------


def test_rerun_same_week_is_idempotent(session) -> None:
    prices = {"AAA": 100.0, "BBB": 200.0}
    broker = FakeBroker(starting_cash=10_000.0, prices=prices)
    common = dict(
        sleeve_name="scanner_only",
        scan_date=SCAN_DATE,
        week_key="2026-W24",
        broker=broker,
        session=session,
        run_scan_fn=_scan(["AAA", "BBB"]),
    )

    run_week(**common)
    cash_after_first = broker.get_account()["cash"]
    orders_after_first = session.query(PaperOrder).count()
    positions_after_first = session.query(PaperPosition).count()

    summary = run_week(**common)

    assert summary["already_ran"] is True
    assert summary["entered"] == []
    assert summary["exited"] == []
    assert summary["n_orders"] == 0
    # Nothing changed broker-side or in the DB.
    assert broker.get_account()["cash"] == pytest.approx(cash_after_first)
    assert session.query(PaperOrder).count() == orders_after_first
    assert session.query(PaperPosition).count() == positions_after_first
    # Exactly one sleeve row — get-or-create did not duplicate it.
    assert session.query(PaperSleeve).count() == 1


# -- 3. aged position exits, new targets enter --------------------------------


def test_aged_position_exits_and_new_targets_enter(session) -> None:
    prices = {"OLD": 100.0, "NEW": 50.0}
    broker = FakeBroker(starting_cash=10_000.0, prices=prices)

    # Seed a sleeve + an open position 40 days old, mirrored broker-side.
    sleeve = PaperSleeve(name="scanner_only", starting_cash=10_000.0)
    session.add(sleeve)
    session.flush()
    entry_date = _days_before(SCAN_DATE, 40)
    session.add(
        PaperPosition(
            sleeve_id=sleeve.id,
            ticker="OLD",
            shares=20.0,
            entry_date=entry_date,
            entry_price=100.0,
            status="open",
        )
    )
    session.commit()
    broker.submit_market_order("OLD", "buy", 20)  # broker now holds 20 OLD

    summary = run_week(
        sleeve_name="scanner_only",
        scan_date=SCAN_DATE,
        week_key="2026-W25",
        broker=broker,
        session=session,
        run_scan_fn=_scan(["NEW"]),
        hold_days=30,
    )

    assert summary["exited"] == ["OLD"]
    assert summary["entered"] == ["NEW"]

    old = session.query(PaperPosition).filter_by(ticker="OLD").one()
    assert old.status == "closed"
    assert old.exit_date == SCAN_DATE
    assert old.exit_price == 100.0

    new = session.query(PaperPosition).filter_by(ticker="NEW", status="open").one()
    assert new.entry_date == SCAN_DATE
    assert new.shares >= 1

    # A sell order for OLD and a buy order for NEW, both filled this week.
    sell = session.query(PaperOrder).filter_by(side="sell", ticker="OLD").one()
    assert sell.status == "filled" and sell.week_key == "2026-W25"
    buy = session.query(PaperOrder).filter_by(side="buy", ticker="NEW").one()
    assert buy.status == "filled" and buy.week_key == "2026-W25"


# -- 4. within-window position is kept ----------------------------------------


def test_within_window_position_is_kept(session) -> None:
    prices = {"HELD": 100.0, "NEW": 50.0}
    broker = FakeBroker(starting_cash=10_000.0, prices=prices)

    sleeve = PaperSleeve(name="scanner_only", starting_cash=10_000.0)
    session.add(sleeve)
    session.flush()
    entry_date = _days_before(SCAN_DATE, 10)  # only 10 days old
    session.add(
        PaperPosition(
            sleeve_id=sleeve.id,
            ticker="HELD",
            shares=20.0,
            entry_date=entry_date,
            entry_price=100.0,
            status="open",
        )
    )
    session.commit()
    broker.submit_market_order("HELD", "buy", 20)

    summary = run_week(
        sleeve_name="scanner_only",
        scan_date=SCAN_DATE,
        week_key="2026-W25",
        broker=broker,
        session=session,
        run_scan_fn=_scan(["NEW"]),
        hold_days=30,
    )

    assert summary["exited"] == []  # under the window — not aged out
    held = session.query(PaperPosition).filter_by(ticker="HELD").one()
    assert held.status == "open"
    assert held.exit_date is None
    # No sell orders were placed at all.
    assert session.query(PaperOrder).filter_by(side="sell").count() == 0


# -- 5. hold_days=None buy-and-hold (spy_benchmark) ---------------------------


def test_hold_days_none_buy_and_hold_never_exits(session) -> None:
    prices = {"SPY": 400.0}
    broker = FakeBroker(starting_cash=10_000.0, prices=prices)
    common = dict(
        sleeve_name="spy_benchmark",
        scan_date=SCAN_DATE,
        broker=broker,
        session=session,
        run_scan_fn=_scan([]),  # benchmark ignores the scan
        hold_days=None,
    )

    week1 = run_week(week_key="2026-W24", **common)
    assert week1["entered"] == ["SPY"]
    spy = session.query(PaperPosition).filter_by(ticker="SPY", status="open").one()
    first_shares = spy.shares
    assert first_shares == 25.0  # floor(10_000 / 400)

    # A later week with a NEW week_key: SPY already held → no new buy, no exit.
    week2 = run_week(week_key="2026-W30", **common)
    assert week2["already_ran"] is False
    assert week2["entered"] == []
    assert week2["exited"] == []
    assert week2["n_orders"] == 0

    # Still exactly one open SPY lot, unchanged, never closed.
    spies = session.query(PaperPosition).filter_by(ticker="SPY").all()
    assert len(spies) == 1
    assert spies[0].status == "open"
    assert spies[0].shares == first_shares


# -- 6. equal-weight share floor ----------------------------------------------


def test_equal_weight_share_floor(session) -> None:
    prices = {"AAA": 100.0, "BBB": 300.0}
    broker = FakeBroker(starting_cash=1_000.0, prices=prices)

    summary = run_week(
        sleeve_name="scanner_only",
        scan_date=SCAN_DATE,
        week_key="2026-W24",
        broker=broker,
        session=session,
        run_scan_fn=_scan(["AAA", "BBB"]),
    )

    # 1000 / 2 = 500 each → floor(500/100)=5 AAA, floor(500/300)=1 BBB.
    positions = {p.ticker: p.shares for p in session.query(PaperPosition).filter_by(status="open").all()}
    assert positions == {"AAA": 5.0, "BBB": 1.0}
    assert sorted(summary["entered"]) == ["AAA", "BBB"]


# -- 7. already-held target is not re-bought ----------------------------------


def test_already_held_target_not_rebought(session) -> None:
    # AAA @300 → floor(10_000/300)=33 shares, cost 9_900, leaving 100 cash so
    # week 2 can still afford a BBB lot (the point being AAA isn't re-bought).
    prices = {"AAA": 300.0, "BBB": 50.0}
    broker = FakeBroker(starting_cash=10_000.0, prices=prices)

    # Week 1: enter AAA only (no age-exit, hold_days large).
    run_week(
        sleeve_name="scanner_only",
        scan_date=SCAN_DATE,
        week_key="2026-W24",
        broker=broker,
        session=session,
        run_scan_fn=_scan(["AAA"]),
        hold_days=365,
    )
    aaa_shares_week1 = session.query(PaperPosition).filter_by(ticker="AAA", status="open").one().shares

    # Week 2: targets include AAA (already held) + BBB (new). AAA must not be
    # bought again; only BBB is entered.
    later = (date.fromisoformat(SCAN_DATE) + timedelta(days=7)).isoformat()
    summary = run_week(
        sleeve_name="scanner_only",
        scan_date=later,
        week_key="2026-W25",
        broker=broker,
        session=session,
        run_scan_fn=_scan(["AAA", "BBB"]),
        hold_days=365,
    )

    assert summary["entered"] == ["BBB"]
    # Exactly one open AAA lot, shares unchanged (no double-buy).
    aaa_lots = session.query(PaperPosition).filter_by(ticker="AAA", status="open").all()
    assert len(aaa_lots) == 1
    assert aaa_lots[0].shares == aaa_shares_week1
    # No buy order for AAA in week 2.
    assert session.query(PaperOrder).filter_by(ticker="AAA", side="buy", week_key="2026-W25").count() == 0
