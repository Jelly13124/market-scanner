"""Offline test for per-sleeve institutional-flow gating in ``run_once``.

The 4th sleeve, ``scanner_agent_flow``, is identical to ``scanner_agent`` EXCEPT
its agent runs with the research agent's institutional-flow context ON, while
``scanner_agent`` runs it OFF — a clean with/without-flow A/B. ``run_once`` is
responsible for toggling that context per sleeve via
``src.research.quant_context.set_flow_enabled`` around each ``compute_targets``
call (where the agent actually runs), and for RESTORING the default (ON) when it
finishes.

This test exercises the REAL flag (it does NOT mock ``set_flow_enabled`` /
``flow_enabled``) through the real reconstruct -> ``run_week`` call graph with a
scratch in-memory SQLite session and ``FakeBroker``. The injected ``agent_fn``
records ``flow_enabled()`` at call-time so we can assert what each agent run saw.

Fully offline: no network, no LLM, no real orders.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.backend.database.connection import Base
from src.paper_trading.run import run_once
from src.paper_trading.sleeves import SLEEVE_NAMES
from src.research import quant_context

SCAN_DATE = "2026-06-08"
WEEK_KEY = "2026-W24"

# Scanner picks (AAA/BBB) + SPY for the benchmark sleeve.
_PRICES = {"AAA": 100.0, "BBB": 50.0, "SPY": 400.0}


@pytest.fixture()
def session():
    """Fresh in-memory SQLite session with the paper-trading tables created."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess
    engine.dispose()


@pytest.fixture(autouse=True)
def _restore_flow_default():
    """Pin the real flow flag to its default before/after each test.

    The test deliberately uses the REAL flag; this guard makes the test
    order-independent and leaves the process flag as it found it.
    """
    quant_context.set_flow_enabled(True)
    try:
        yield
    finally:
        quant_context.set_flow_enabled(True)


def _run_scan_fn(scan_date: str, top_n: int) -> list[str]:
    """Stub scanner: a fixed ranked basket capped at ``top_n``."""
    return ["AAA", "BBB"][:top_n]


def _price_fn(ticker: str) -> float | None:
    """Stub price feed: look up the static book; None for unknowns."""
    return _PRICES.get(ticker)


def test_run_once_gates_flow_per_sleeve_and_restores_default(session) -> None:
    # The agent records what flow_enabled() returned each time it was called,
    # in call order. Only the agent sleeves (scanner_agent, scanner_agent_flow)
    # invoke it, so we get exactly two observations in SLEEVE_NAMES order.
    observed_flow: list[bool] = []

    def _agent_fn(tickers: list[str], scan_date: str) -> dict[str, dict]:
        observed_flow.append(quant_context.flow_enabled())
        return {t: {"action": "buy"} for t in tickers}

    summaries = run_once(
        session=session,
        run_scan_fn=_run_scan_fn,
        agent_fn=_agent_fn,
        price_fn=_price_fn,
        scan_date=SCAN_DATE,
        week_key=WEEK_KEY,
        top_n=5,
    )

    # All four sleeves ran cleanly (no per-sleeve error entries).
    assert set(summaries) == set(SLEEVE_NAMES)
    assert all("error" not in s for s in summaries.values()), summaries

    # The agent ran exactly twice: scanner_agent (flow OFF) then, later in
    # SLEEVE_NAMES order, scanner_agent_flow (flow ON). Order is deterministic
    # because SLEEVE_NAMES is a fixed tuple iterated in order.
    assert observed_flow == [False, True]
    # And as a set, both with/without-flow arms were exercised.
    assert set(observed_flow) == {False, True}

    # After run_once returns, the default (flow ON for normal Analyze) is back.
    assert quant_context.flow_enabled() is True


def test_run_once_restores_flow_default_even_when_a_sleeve_raises(session) -> None:
    """The finally-restore fires even if a sleeve's agent blows up mid-run.

    Force flow OFF before the call (simulating leftover state), make the
    scanner_agent agent raise so the gate has flipped to OFF, and confirm the
    flag is still restored to the default ON on return.
    """
    quant_context.set_flow_enabled(False)

    def _boom_agent(tickers: list[str], scan_date: str) -> dict[str, dict]:
        raise RuntimeError("agent exploded")

    summaries = run_once(
        session=session,
        run_scan_fn=_run_scan_fn,
        agent_fn=_boom_agent,
        price_fn=_price_fn,
        scan_date=SCAN_DATE,
        week_key=WEEK_KEY,
        top_n=5,
    )

    # compute_targets swallows the agent raise (no conviction), so the run still
    # completes for every sleeve rather than erroring out.
    assert set(summaries) == set(SLEEVE_NAMES)

    # Restored to the default regardless of the mid-run agent failure.
    assert quant_context.flow_enabled() is True
