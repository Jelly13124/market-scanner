"""run_once honors the PAPER_SLEEVES gate (offline).

Proves the unattended runner only iterates the sleeves named in PAPER_SLEEVES,
so the heavy ``factor_evolved`` sleeve can be excluded on prod. No network/LLM:
the seams are no-op stubs and the DB is a scratch in-memory SQLite (the same
scaffolding as test_smoke.py).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.backend.database.connection import Base
from app.backend.database.models import PaperSleeve
from src.paper_trading import run as run_mod


@pytest.fixture()
def session():
    """Fresh in-memory SQLite session with the paper-trading tables created."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess
    engine.dispose()


def test_run_once_only_runs_active_sleeves(monkeypatch, session) -> None:
    """PAPER_SLEEVES set to a 2-sleeve subset -> run_once touches only those.

    The seams are deliberately minimal: a one-name scan, an empty agent, an empty
    factor book, and a flat price. That is enough to prove the ITERATION SET
    (which sleeves get a summary + a DB row) without any live data.
    """
    monkeypatch.setenv("PAPER_SLEEVES", "spy_benchmark,scanner_only")

    def run_scan_fn(scan_date, top_n):
        return ["AAA"][:top_n]

    def agent_fn(tickers, scan_date):
        return {}

    def factor_fn(scan_date):
        return []

    def price_fn(ticker):
        return 100.0  # priceable so the active sleeves can deploy

    summaries = run_mod.run_once(
        session=session,
        run_scan_fn=run_scan_fn,
        agent_fn=agent_fn,
        factor_fn=factor_fn,
        price_fn=price_fn,
        scan_date="2026-06-10",
        week_key="2026-W24",
    )

    assert set(summaries.keys()) == {"spy_benchmark", "scanner_only"}
    # Only the active sleeves were seeded into the DB; factor_evolved (and the
    # agent sleeves) were never iterated.
    seeded = {s.name for s in session.query(PaperSleeve).all()}
    assert seeded == {"spy_benchmark", "scanner_only"}
    assert "factor_evolved" not in seeded
