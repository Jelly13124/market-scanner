"""Offline tests for per-sleeve performance + the graduation bar (Task 6).

Fully offline: a scratch in-memory SQLite engine + ``Session`` (same setup as
``test_marks.py``) seeded with equity marks and closed positions. No network, no
LLM — every number is reconstructed from the DB, which is the whole point of the
architecture.

The cases pin the load-bearing contracts:
  * total_return is measured against ``starting_cash`` and signed correctly;
  * ``n_trades`` counts only CLOSED positions;
  * sharpe/max_drawdown come from the reused calculator with a real ``datetime``
    Date, and max_drawdown is a percent (``abs < 100``) — NOT multiplied by 100
    twice;
  * fewer than two marks yields ``None`` metric fields without crashing; and
  * the graduation verdict PASSes only when all four clauses hold, FAILs one
    clause at a time, and treats a missing ``scanner_agent`` as a clean FAIL.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.backend.database.connection import Base
from app.backend.database.models import (
    PaperEquityMark,
    PaperPosition,
    PaperSleeve,
)
from src.paper_trading.performance import (
    compute_performance,
    evaluate_graduation,
    sleeve_metrics,
)


# -- fixtures / helpers -------------------------------------------------------


@pytest.fixture()
def session():
    """Fresh in-memory SQLite session with the paper-trading tables created."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess
    engine.dispose()


def _make_sleeve(session, name: str, starting_cash: float = 100_000.0) -> PaperSleeve:
    sleeve = PaperSleeve(name=name, starting_cash=starting_cash)
    session.add(sleeve)
    session.flush()  # assign sleeve.id
    return sleeve


def _add_marks(session, sleeve_id, equities, *, start_day: int = 1) -> None:
    """Seed consecutive daily marks (2026-06-0X) for a sleeve."""
    for offset, equity in enumerate(equities):
        date = f"2026-06-{start_day + offset:02d}"
        session.add(PaperEquityMark(sleeve_id=sleeve_id, date=date, equity=float(equity)))


def _add_closed_position(session, sleeve_id, ticker, shares=10.0, entry=100.0, exit_=110.0) -> None:
    session.add(
        PaperPosition(
            sleeve_id=sleeve_id,
            ticker=ticker,
            shares=shares,
            entry_date="2026-06-01",
            entry_price=entry,
            exit_date="2026-06-05",
            exit_price=exit_,
            status="closed",
        )
    )


def _add_open_position(session, sleeve_id, ticker, shares=10.0, entry=100.0) -> None:
    session.add(
        PaperPosition(
            sleeve_id=sleeve_id,
            ticker=ticker,
            shares=shares,
            entry_date="2026-06-01",
            entry_price=entry,
            status="open",
        )
    )


# -- 1. sleeve_metrics happy path: rising curve + 2 closed positions ----------


def test_sleeve_metrics_rising_curve(session) -> None:
    sleeve = _make_sleeve(session, "scanner_agent", 100_000.0)
    # Rising curve with a mid dip so drawdown is a real (negative) percent.
    _add_marks(session, sleeve.id, [100_000.0, 102_000.0, 101_000.0, 105_000.0])
    _add_closed_position(session, sleeve.id, "AAA")
    _add_closed_position(session, sleeve.id, "BBB")
    # An OPEN position must NOT count toward n_trades.
    _add_open_position(session, sleeve.id, "CCC")
    session.commit()

    m = sleeve_metrics("scanner_agent", session=session)

    assert m["n_marks"] == 4
    assert m["n_trades"] == 2  # only the two closed round-trips
    assert m["final_equity"] == pytest.approx(105_000.0)
    # Rising overall: 105k / 100k - 1 = +0.05.
    assert m["total_return"] == pytest.approx(0.05)
    assert m["total_return"] > 0
    assert m["sharpe"] is not None
    # Drawdown is a percent from the 102k -> 101k dip; ~ -0.98%. Must be a
    # percent (abs < 100), NOT multiplied by 100 twice, and negative here.
    assert m["max_drawdown"] is not None
    assert m["max_drawdown"] < 0
    assert abs(m["max_drawdown"]) < 100
    assert m["max_drawdown"] == pytest.approx((101_000.0 - 102_000.0) / 102_000.0 * 100.0, rel=1e-6)


# -- 2. fewer than two marks → metric fields None, no crash -------------------


def test_sleeve_metrics_too_few_marks(session) -> None:
    sleeve = _make_sleeve(session, "scanner_agent", 100_000.0)
    _add_marks(session, sleeve.id, [101_000.0])  # single mark
    session.commit()

    m = sleeve_metrics("scanner_agent", session=session)

    assert m["n_marks"] == 1
    # final_equity / total_return still derivable from the single mark...
    assert m["final_equity"] == pytest.approx(101_000.0)
    assert m["total_return"] == pytest.approx(0.01)
    # ...but sharpe/max_drawdown need >= 2 marks → None, no crash.
    assert m["sharpe"] is None
    assert m["max_drawdown"] is None


def test_sleeve_metrics_no_marks(session) -> None:
    _make_sleeve(session, "scanner_agent", 100_000.0)
    session.commit()

    m = sleeve_metrics("scanner_agent", session=session)

    assert m["n_marks"] == 0
    assert m["final_equity"] is None
    assert m["total_return"] is None
    assert m["sharpe"] is None
    assert m["max_drawdown"] is None
    assert m["n_trades"] == 0


def test_sleeve_metrics_unknown_sleeve(session) -> None:
    m = sleeve_metrics("does_not_exist", session=session)
    assert m["n_marks"] == 0
    assert m["final_equity"] is None
    assert m["total_return"] is None


# -- compute_performance fan-out ----------------------------------------------


def test_compute_performance_covers_every_sleeve(session) -> None:
    a = _make_sleeve(session, "scanner_agent")
    o = _make_sleeve(session, "scanner_only")
    s = _make_sleeve(session, "spy_benchmark")
    _add_marks(session, a.id, [100_000.0, 103_000.0])
    _add_marks(session, o.id, [100_000.0, 101_000.0])
    _add_marks(session, s.id, [100_000.0, 100_500.0])
    session.commit()

    perf = compute_performance(session)

    assert set(perf.keys()) == {"scanner_agent", "scanner_only", "spy_benchmark"}
    assert perf["scanner_agent"]["total_return"] == pytest.approx(0.03)
    assert perf["scanner_only"]["total_return"] == pytest.approx(0.01)
    assert perf["spy_benchmark"]["total_return"] == pytest.approx(0.005)


# -- 3. evaluate_graduation PASS ----------------------------------------------


def _perf(agent=None, only=None, spy=None) -> dict:
    """Assemble a perf dict from partial per-sleeve metric overrides."""
    base = {
        "total_return": 0.0,
        "sharpe": 0.0,
        "max_drawdown": 0.0,
        "n_trades": 0,
        "final_equity": 100_000.0,
        "n_marks": 2,
    }
    out = {}
    if agent is not None:
        out["scanner_agent"] = {**base, **agent}
    if only is not None:
        out["scanner_only"] = {**base, **only}
    if spy is not None:
        out["spy_benchmark"] = {**base, **spy}
    return out


def test_evaluate_graduation_pass(session) -> None:
    perf = _perf(
        agent={"total_return": 0.08, "sharpe": 1.5, "max_drawdown": -8.0},
        only={"total_return": 0.04},
        spy={"sharpe": 1.0},
    )
    verdict = evaluate_graduation(perf)

    assert verdict["passed"] is True
    assert all(verdict["checked_clauses"].values())
    assert all(r.startswith("PASS") for r in verdict["reasons"])


# -- 4. four FAIL cases, one per clause ---------------------------------------


def test_evaluate_graduation_fail_negative_return(session) -> None:
    perf = _perf(
        agent={"total_return": -0.02, "sharpe": 1.5, "max_drawdown": -8.0},
        only={"total_return": -0.05},  # agent still beats only, so only this clause fails
        spy={"sharpe": 1.0},
    )
    verdict = evaluate_graduation(perf)

    assert verdict["passed"] is False
    assert verdict["checked_clauses"]["positive_return"] is False
    # The other three clauses still pass — isolates the failing clause.
    assert verdict["checked_clauses"]["sharpe_beats_spy"] is True
    assert verdict["checked_clauses"]["drawdown_under_20"] is True
    assert verdict["checked_clauses"]["return_beats_scanner_only"] is True


def test_evaluate_graduation_fail_sharpe_below_spy(session) -> None:
    perf = _perf(
        agent={"total_return": 0.08, "sharpe": 0.5, "max_drawdown": -8.0},
        only={"total_return": 0.04},
        spy={"sharpe": 1.0},  # agent sharpe 0.5 < spy 1.0
    )
    verdict = evaluate_graduation(perf)

    assert verdict["passed"] is False
    assert verdict["checked_clauses"]["sharpe_beats_spy"] is False
    assert verdict["checked_clauses"]["positive_return"] is True


def test_evaluate_graduation_fail_drawdown_breaches_20(session) -> None:
    perf = _perf(
        agent={"total_return": 0.08, "sharpe": 1.5, "max_drawdown": -25.0},  # 25% > 20%
        only={"total_return": 0.04},
        spy={"sharpe": 1.0},
    )
    verdict = evaluate_graduation(perf)

    assert verdict["passed"] is False
    assert verdict["checked_clauses"]["drawdown_under_20"] is False
    assert verdict["checked_clauses"]["positive_return"] is True


def test_evaluate_graduation_fail_return_below_scanner_only(session) -> None:
    perf = _perf(
        agent={"total_return": 0.03, "sharpe": 1.5, "max_drawdown": -8.0},
        only={"total_return": 0.06},  # agent 0.03 < scanner_only 0.06
        spy={"sharpe": 1.0},
    )
    verdict = evaluate_graduation(perf)

    assert verdict["passed"] is False
    assert verdict["checked_clauses"]["return_beats_scanner_only"] is False
    assert verdict["checked_clauses"]["positive_return"] is True


# -- 5. missing scanner_agent metrics → FAIL, no crash ------------------------


def test_evaluate_graduation_missing_agent(session) -> None:
    # No scanner_agent key at all.
    perf = _perf(only={"total_return": 0.04}, spy={"sharpe": 1.0})
    verdict = evaluate_graduation(perf)

    assert verdict["passed"] is False
    # Every clause that depends on the agent fails cleanly (no KeyError).
    assert verdict["checked_clauses"]["positive_return"] is False
    assert verdict["checked_clauses"]["sharpe_beats_spy"] is False
    assert verdict["checked_clauses"]["drawdown_under_20"] is False
    assert verdict["checked_clauses"]["return_beats_scanner_only"] is False


def test_evaluate_graduation_agent_none_metrics(session) -> None:
    # scanner_agent present but its metrics are None (e.g. < 2 marks).
    perf = _perf(
        agent={"total_return": None, "sharpe": None, "max_drawdown": None},
        only={"total_return": 0.04},
        spy={"sharpe": 1.0},
    )
    verdict = evaluate_graduation(perf)

    assert verdict["passed"] is False
    assert verdict["checked_clauses"]["positive_return"] is False
    assert verdict["checked_clauses"]["sharpe_beats_spy"] is False
    assert verdict["checked_clauses"]["drawdown_under_20"] is False
