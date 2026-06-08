"""Regression tests for the two final-review fixes:

  * CRITICAL — `spy_benchmark` must be buy-and-hold: `run_once` passes
    `hold_days=None` for that sleeve so SPY never ages out / churns.
  * MEDIUM — equal-weight entry must split cash only across PRICEABLE targets,
    so an unpriceable name doesn't leave its capital idle (A/B bias).

All offline: scratch in-memory SQLite + trivial stubs.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.backend.database.models import (
    Base,
    PaperOrder,
    PaperPosition,
    PaperSleeve,
)
from src.paper_trading import run as paper_run
from src.paper_trading.broker import FakeBroker
from src.paper_trading.engine import run_week


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess


# -- CRITICAL: spy_benchmark buy-and-hold ------------------------------------

_PRICES = {"AAA": 100.0, "BBB": 50.0, "SPY": 400.0}


def _scan(scan_date, top_n):
    return ["AAA", "BBB"][:top_n]


def _agent(tickers, scan_date):
    return {t: {"action": "buy"} for t in tickers}


def _price(ticker):
    return _PRICES.get(ticker)


def test_spy_benchmark_is_buy_and_hold_across_weeks(session):
    # Week 1: all sleeves enter.
    paper_run.run_once(
        session=session,
        run_scan_fn=_scan,
        agent_fn=_agent,
        price_fn=_price,
        scan_date="2026-01-05",
        week_key="2026-W01",
        hold_days=30,
    )
    # Week 2, >30 calendar days later. The active sleeves age out; spy must NOT
    # (this is exactly the bug the fix addresses — without hold_days=None for
    # spy, SPY would be sold here and re-bought, breaking the benchmark).
    paper_run.run_once(
        session=session,
        run_scan_fn=_scan,
        agent_fn=_agent,
        price_fn=_price,
        scan_date="2026-02-20",
        week_key="2026-W08",
        hold_days=30,
    )

    spy = session.query(PaperSleeve).filter_by(name="spy_benchmark").one()
    sells = session.query(PaperOrder).filter_by(sleeve_id=spy.id, side="sell").count()
    assert sells == 0, "spy_benchmark must never sell — it is buy-and-hold"
    open_spy = session.query(PaperPosition).filter_by(sleeve_id=spy.id, ticker="SPY", status="open").count()
    assert open_spy == 1, "the single SPY lot must stay open across weeks"


# -- MEDIUM: equal-weight redistributes across priceable targets only --------


def test_equal_weight_uses_only_priceable_targets(session):
    # scanner_only targets AAA + BBB, but the broker can only price AAA.
    # Fixed behaviour: AAA gets the FULL cash (notional = 1000/1) → 10 shares,
    # not half (notional = 1000/2 → 5 shares).
    broker = FakeBroker(starting_cash=1000.0, prices={"AAA": 100.0})
    run_week(
        sleeve_name="scanner_only",
        scan_date="2026-01-05",
        week_key="2026-W01",
        broker=broker,
        session=session,
        run_scan_fn=lambda d, n: ["AAA", "BBB"],
        agent_fn=None,
        top_n=2,
        hold_days=30,
    )
    pos = session.query(PaperPosition).filter_by(ticker="AAA", status="open").one()
    assert pos.shares == 10.0, "unpriceable BBB's capital must redistribute to AAA"
    assert session.query(PaperPosition).filter_by(ticker="BBB").count() == 0
