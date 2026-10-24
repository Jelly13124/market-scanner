"""Per-sleeve performance + graduation-bar verdict for the forward test (Task 6).

The daily mark (Task 5) persists one :class:`PaperEquityMark` per ``(sleeve, date)``.
This module reads those marks back, reconstructs each sleeve's equity curve, and
derives the comparable A/B numbers — total return, sharpe, max drawdown, trade
count — that decide whether the ``scanner_agent`` book has earned a path to real
money.

Metrics reuse the already-debugged :class:`PerformanceMetricsCalculator` exactly
as ``v2/workflow_backtest/portfolio.py`` does, including its two load-bearing
gotchas:
  * the equity curve passes a real ``datetime`` for ``Date`` (parsed from the
    stored ``YYYY-MM-DD`` string), so ``idxmin().strftime`` does not crash on a
    real drawdown; and
  * the calculator already returns ``max_drawdown`` multiplied by 100 (a
    percent), so it is passed through as-is — never multiplied by 100 again.

Robustness contract (mirrors the rest of the harness): nothing here raises on a
sleeve with too few marks, a missing sleeve, or a per-sleeve metric failure.
``compute_performance`` isolates each sleeve so one bad book never aborts the
others, and ``evaluate_graduation`` turns a missing/None metric into a FAILed
clause rather than a crash.
"""

from __future__ import annotations

import datetime as _dt
import logging

from sqlalchemy.orm import Session

from src.backtesting.metrics import PerformanceMetricsCalculator
from app.backend.database.models import (
    PaperEquityMark,
    PaperPosition,
    PaperSleeve,
)

logger = logging.getLogger(__name__)


def sleeve_metrics(sleeve_name: str, *, session: Session) -> dict:
    """Compute one sleeve's performance from its persisted equity marks.

    Loads this sleeve's :class:`PaperEquityMark` rows ordered by date and builds
    the ``[{"Date": datetime, "Portfolio Value": equity}, ...]`` curve the
    metrics calculator expects (the stored ``YYYY-MM-DD`` strings are parsed to
    real ``datetime`` so the drawdown date does not crash). At least two marks
    are needed for sharpe/drawdown; with fewer, the metric fields come back
    ``None`` (only ``n_trades``/``n_marks``/``final_equity`` are populated).

    ``total_return`` is measured against the sleeve's ``starting_cash`` (the
    deposited capital), not the first mark, so it reflects return on the money
    actually put in even if the first mark already drifted.

    Args:
        sleeve_name: The sleeve to evaluate (resolved by unique ``name``).
        session: SQLAlchemy session for the paper-trading tables.

    Returns:
        ``{"total_return", "sharpe", "max_drawdown", "n_trades",
        "final_equity", "n_marks"}``. ``total_return``/``sharpe``/
        ``max_drawdown``/``final_equity`` are ``None`` when they cannot be
        computed (unknown sleeve, or fewer than the marks required). Never raises.
    """
    result = {
        "total_return": None,
        "sharpe": None,
        "max_drawdown": None,
        "n_trades": 0,
        "final_equity": None,
        "n_marks": 0,
    }

    sleeve = session.query(PaperSleeve).filter_by(name=sleeve_name).one_or_none()
    if sleeve is None:
        logger.warning("sleeve_metrics: no sleeve named %r; returning empty metrics", sleeve_name)
        return result

    # Completed round-trips: closed positions for this sleeve.
    result["n_trades"] = session.query(PaperPosition).filter_by(sleeve_id=sleeve.id, status="closed").count()

    marks = session.query(PaperEquityMark).filter_by(sleeve_id=sleeve.id).order_by(PaperEquityMark.date).all()
    result["n_marks"] = len(marks)
    if not marks:
        return result

    final_equity = float(marks[-1].equity)
    result["final_equity"] = final_equity

    # total_return against deposited capital (starting_cash), per Task 6 contract.
    starting_cash = float(sleeve.starting_cash)
    if starting_cash != 0:
        result["total_return"] = final_equity / starting_cash - 1.0

    # Need >= 2 marks for the calculator to produce sharpe/drawdown.
    if len(marks) < 2:
        return result

    # Real datetime Date (gotcha a) so idxmin().strftime survives a real drawdown.
    curve = [{"Date": _dt.datetime.fromisoformat(m.date[:10]), "Portfolio Value": float(m.equity)} for m in marks]
    metrics = PerformanceMetricsCalculator().compute_metrics(curve)
    result["sharpe"] = metrics.get("sharpe_ratio")
    # gotcha b: max_drawdown is ALREADY a ×100 percent — pass through as-is.
    result["max_drawdown"] = metrics.get("max_drawdown")

    return result


def compute_performance(session: Session) -> dict[str, dict]:
    """Compute :func:`sleeve_metrics` for every sleeve in the book.

    Iterates all :class:`PaperSleeve` rows. A sleeve whose metrics raise is
    logged and skipped (its key omitted) so one bad book never aborts the A/B.

    Args:
        session: SQLAlchemy session for the paper-trading tables.

    Returns:
        ``{sleeve_name: sleeve_metrics(...)}`` for every sleeve evaluated
        successfully. Never raises.
    """
    perf: dict[str, dict] = {}
    sleeves = session.query(PaperSleeve).all()
    for sleeve in sleeves:
        try:
            perf[sleeve.name] = sleeve_metrics(sleeve.name, session=session)
        except Exception:
            logger.exception("compute_performance: metrics raised for %s; skipping", sleeve.name)
            continue
    return perf


def evaluate_graduation(perf: dict[str, dict]) -> dict:
    """Evaluate the graduation bar that gates moving to real money.

    The ``scanner_agent`` sleeve graduates only when it simultaneously:
      1. has a positive total return,
      2. matches or beats the ``spy_benchmark`` sleeve's sharpe,
      3. keeps its max drawdown shallower than 20% (``abs(max_drawdown) < 20`` —
         drawdown is a ×100 percent whose sign may be negative), and
      4. matches or beats the ``scanner_only`` sleeve's total return.

    Any clause whose required metric is missing or ``None`` FAILs that clause
    (rather than crashing), forcing ``passed`` to ``False``.

    Args:
        perf: ``{sleeve_name: metrics}`` as returned by :func:`compute_performance`.

    Returns:
        ``{"passed": bool, "reasons": list[str], "checked_clauses": dict}`` where
        ``reasons`` holds one ``"PASS: ..."``/``"FAIL: ..."`` line per clause and
        ``checked_clauses`` maps a clause key to its boolean verdict.
    """
    agent = perf.get("scanner_agent") or {}
    spy = perf.get("spy_benchmark") or {}
    only = perf.get("scanner_only") or {}

    agent_return = agent.get("total_return")
    agent_sharpe = agent.get("sharpe")
    agent_dd = agent.get("max_drawdown")
    spy_sharpe = spy.get("sharpe")
    only_return = only.get("total_return")

    reasons: list[str] = []
    clauses: dict[str, bool] = {}

    # Clause 1: positive total return.
    if agent_return is None:
        clauses["positive_return"] = False
        reasons.append("FAIL: scanner_agent total_return missing")
    elif agent_return > 0:
        clauses["positive_return"] = True
        reasons.append(f"PASS: scanner_agent total_return {agent_return:.4f} > 0")
    else:
        clauses["positive_return"] = False
        reasons.append(f"FAIL: scanner_agent total_return {agent_return:.4f} <= 0")

    # Clause 2: sharpe >= spy_benchmark sharpe.
    if agent_sharpe is None or spy_sharpe is None:
        clauses["sharpe_beats_spy"] = False
        reasons.append(f"FAIL: sharpe comparison missing (agent={agent_sharpe}, spy={spy_sharpe})")
    elif agent_sharpe >= spy_sharpe:
        clauses["sharpe_beats_spy"] = True
        reasons.append(f"PASS: scanner_agent sharpe {agent_sharpe:.4f} >= spy {spy_sharpe:.4f}")
    else:
        clauses["sharpe_beats_spy"] = False
        reasons.append(f"FAIL: scanner_agent sharpe {agent_sharpe:.4f} < spy {spy_sharpe:.4f}")

    # Clause 3: max drawdown shallower than 20% (abs < 20; DD is a ×100 percent).
    if agent_dd is None:
        clauses["drawdown_under_20"] = False
        reasons.append("FAIL: scanner_agent max_drawdown missing")
    elif abs(agent_dd) < 20:
        clauses["drawdown_under_20"] = True
        reasons.append(f"PASS: scanner_agent max_drawdown {agent_dd:.2f}% within 20%")
    else:
        clauses["drawdown_under_20"] = False
        reasons.append(f"FAIL: scanner_agent max_drawdown {agent_dd:.2f}% breaches 20%")

    # Clause 4: total return >= scanner_only total return.
    if agent_return is None or only_return is None:
        clauses["return_beats_scanner_only"] = False
        reasons.append(f"FAIL: return comparison missing (agent={agent_return}, scanner_only={only_return})")
    elif agent_return >= only_return:
        clauses["return_beats_scanner_only"] = True
        reasons.append(f"PASS: scanner_agent total_return {agent_return:.4f} >= scanner_only {only_return:.4f}")
    else:
        clauses["return_beats_scanner_only"] = False
        reasons.append(f"FAIL: scanner_agent total_return {agent_return:.4f} < scanner_only {only_return:.4f}")

    passed = all(clauses.values())
    return {"passed": passed, "reasons": reasons, "checked_clauses": clauses}
