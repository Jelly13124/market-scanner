"""Offline end-to-end smoke test for the paper-trading harness (Task 8).

Exercises the whole wired system with ZERO live dependencies:
  * a scratch in-memory SQLite engine + Session (the source of truth),
  * per-sleeve ``FakeBroker`` ledgers rebuilt via ``reconstruct_broker``,
  * trivial in-process ``run_scan_fn`` / ``agent_fn`` / ``price_fn`` stubs.

It walks the real call graph a live run would: reconstruct → ``run_week`` for all
three sleeves for one week → ``mark_all`` → ``compute_performance`` +
``evaluate_graduation`` → ``write_report``. Then it asserts the state
materialized, the report files exist, the week is idempotent on re-run, and —
critically — that NOTHING imported ``alpaca`` along the way (the offline suite
must never pull the optional live SDK).

No network, no LLM, no real orders, no ``alpaca-py``.
"""

from __future__ import annotations

import sys

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
from src.paper_trading.engine import run_week
from src.paper_trading.marks import mark_all
from src.paper_trading.performance import compute_performance, evaluate_graduation
from src.paper_trading.report import write_report
from src.paper_trading.sleeves import SLEEVE_NAMES
from src.paper_trading.state import reconstruct_broker

SCAN_DATE = "2026-06-08"
WEEK_KEY = "2026-W24"

# Stub price book: the scanner picks (AAA/BBB) + SPY for the benchmark sleeve.
_PRICES = {"AAA": 100.0, "BBB": 50.0, "SPY": 400.0}


# -- fixtures / stubs ---------------------------------------------------------


@pytest.fixture()
def session():
    """Fresh in-memory SQLite session with the paper-trading tables created."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess
    engine.dispose()


def _run_scan_fn(scan_date: str, top_n: int) -> list[str]:
    """Stub scanner: a fixed ranked basket capped at ``top_n``."""
    return ["AAA", "BBB"][:top_n]


def _agent_fn(tickers: list[str], scan_date: str) -> dict[str, dict]:
    """Stub agent: buy both picks (so scanner_agent has conviction)."""
    return {t: {"action": "buy"} for t in tickers}


def _factor_fn(scan_date: str) -> list[str]:
    """Stub self-evolved factor book: hold the same priced names (so the
    factor_evolved sleeve has conviction in the offline smoke)."""
    return ["AAA", "BBB"]


def _price_fn(ticker: str) -> float | None:
    """Stub price feed: look up the static book; None for unknowns."""
    return _PRICES.get(ticker)


def _drive_week(session) -> dict[str, dict]:
    """Reconstruct each sleeve's broker from the DB and run one week.

    Mirrors ``run.run_once`` but with the offline stubs and the static price
    book, so it stands in for the live runner without any provider/LLM calls.
    """
    summaries: dict[str, dict] = {}
    for sleeve_name in SLEEVE_NAMES:
        broker = reconstruct_broker(sleeve_name, session, prices=dict(_PRICES))
        # spy_benchmark holds forever (hold_days=None); the others age out at 30d.
        hold_days = None if sleeve_name == "spy_benchmark" else 30
        summaries[sleeve_name] = run_week(
            sleeve_name=sleeve_name,
            scan_date=SCAN_DATE,
            week_key=WEEK_KEY,
            broker=broker,
            session=session,
            run_scan_fn=_run_scan_fn,
            agent_fn=_agent_fn,
            factor_fn=_factor_fn,
            top_n=5,
            hold_days=hold_days,
        )
    return summaries


# -- the smoke ----------------------------------------------------------------


def test_offline_end_to_end_smoke(session, tmp_path) -> None:
    # --- 1. Weekly rebalance for all three sleeves. --------------------------
    summaries = _drive_week(session)

    assert set(summaries) == set(SLEEVE_NAMES)
    # scanner_agent + scanner_only buy AAA/BBB; spy_benchmark buys SPY.
    assert set(summaries["scanner_agent"]["entered"]) == {"AAA", "BBB"}
    assert set(summaries["scanner_only"]["entered"]) == {"AAA", "BBB"}
    assert summaries["spy_benchmark"]["entered"] == ["SPY"]
    assert all(not s["already_ran"] for s in summaries.values())

    # --- 2. State materialized in the DB. -----------------------------------
    sleeves = {s.name: s for s in session.query(PaperSleeve).all()}
    assert set(sleeves) == set(SLEEVE_NAMES)

    for name in SLEEVE_NAMES:
        sid = sleeves[name].id
        open_positions = session.query(PaperPosition).filter_by(sleeve_id=sid, status="open").all()
        orders = session.query(PaperOrder).filter_by(sleeve_id=sid).all()
        assert open_positions, f"{name} should hold open positions"
        assert orders, f"{name} should have recorded orders"
        assert all(o.week_key == WEEK_KEY for o in orders)
        assert all(o.status == "filled" for o in orders)

    # --- 3. Daily mark-to-market for all sleeves. ---------------------------
    equities = mark_all(SCAN_DATE, session=session, price_fn=_price_fn)
    assert set(equities) == set(SLEEVE_NAMES)
    for name in SLEEVE_NAMES:
        marks = session.query(PaperEquityMark).filter_by(sleeve_id=sleeves[name].id).all()
        assert len(marks) == 1  # one upserted mark for SCAN_DATE
        # Equity ≈ starting_cash (bought equal-weight, marked at entry prices).
        assert equities[name] == pytest.approx(100_000.0, rel=0.05)

    # --- 4. Performance + graduation verdict (must not raise). --------------
    perf = compute_performance(session)
    assert set(perf) == set(SLEEVE_NAMES)
    for name in SLEEVE_NAMES:
        # Final equity is populated even with a single mark.
        assert perf[name]["final_equity"] is not None
        assert perf[name]["n_marks"] == 1

    verdict = evaluate_graduation(perf)
    assert "passed" in verdict
    assert isinstance(verdict["reasons"], list) and verdict["reasons"]
    # One mark => no sharpe/drawdown => graduation cannot pass. That's expected;
    # we only assert it evaluated cleanly, not the boolean.
    assert verdict["passed"] is False

    # --- 5. Report files written. -------------------------------------------
    out = write_report(str(tmp_path), session=session)
    assert out["report_md"].endswith("paper_trading_report.md")
    assert out["report_html"].endswith("paper_trading_report.html")
    assert (tmp_path / "paper_trading_report.md").exists()
    assert (tmp_path / "paper_trading_report.html").exists()
    md_text = (tmp_path / "paper_trading_report.md").read_text(encoding="utf-8")
    assert "Paper Trading Forward-Test Report" in md_text
    for name in SLEEVE_NAMES:
        assert name in md_text  # every sleeve appears in the metrics table

    # --- 6. Re-running the same week is idempotent. -------------------------
    orders_before = session.query(PaperOrder).count()
    positions_before = session.query(PaperPosition).count()
    rerun = _drive_week(session)
    assert all(s["already_ran"] for s in rerun.values())
    assert all(s["n_orders"] == 0 for s in rerun.values())
    assert session.query(PaperOrder).count() == orders_before
    assert session.query(PaperPosition).count() == positions_before

    # --- 7. The offline path NEVER imported alpaca-py. ----------------------
    assert "alpaca" not in sys.modules
    assert not any(m == "alpaca" or m.startswith("alpaca.") for m in sys.modules)
