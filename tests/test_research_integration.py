"""End-to-end integration: POST /research/run actually persists, GET
list/detail/html all return consistent data. Uses in-memory SQLite +
mocked LLM."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backend.auth.dependencies import get_current_user
from app.backend.database.connection import Base, get_db
from app.backend.database.models import User
from app.backend.main import app
from src.research.models import (
    BacktestSummary, ResearchRequest, ResearchState, TradePlan,
)


@pytest.fixture
def client():
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def _override_get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    # Superuser: the legacy /research/run route is superuser-only (regular users
    # get 403). This end-to-end flow exercises run → list → detail → html, so the
    # acting user must be a superuser to reach the run path.
    _fake_user = User(id=1, email="test@test.com", is_active=True, is_superuser=True)

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = lambda: _fake_user
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


def _fake_state(ticker="NVDA", direction="long"):
    return ResearchState(
        request=ResearchRequest(
            ticker=ticker, holding_status="watching",
            target_position_pct=0.05, risk_tolerance="moderate",
            report_goal="new_entry", use_personas=False,
            scanner_context=None,
        ),
        persona_assignments=None,
        module_results={},
        report_markdown=f"# {ticker} report\n\nBody.",
        strategy=TradePlan(
            direction=direction,
            entry_price=145.0 if direction != "stand_aside" else None,
            target_price=165.0 if direction != "stand_aside" else None,
            stop_price=138.0 if direction != "stand_aside" else None,
            horizon_days=30 if direction != "stand_aside" else 0,
            sizing_pct=0.05 if direction != "stand_aside" else 0.0,
            confidence=72 if direction != "stand_aside" else 0,
            rationale="r",
        ),
        backtest_summary=BacktestSummary(
            matches_found=5, win_rate=0.6, avg_pnl_pct=0.08,
            max_drawdown_pct=-0.10, avg_holding_days=20.0,
            sample_quality="moderate", caveat=None,
        ),
        rendered_html=None,
    )


class TestEndToEndFlow:
    @patch("app.backend.routes.research.run_research")
    def test_post_then_list_then_detail_then_html(self, mock_run, client):
        mock_run.return_value = _fake_state("NVDA")
        # POST
        r1 = client.post("/research/run", json={"ticker": "nvda"})
        assert r1.status_code == 200
        report_id = r1.json()["id"]
        assert r1.json()["ticker"] == "NVDA"  # uppercased

        # LIST
        r2 = client.get("/research/reports")
        assert r2.status_code == 200
        summaries = r2.json()
        assert any(s["id"] == report_id for s in summaries)

        # DETAIL
        r3 = client.get(f"/research/reports/{report_id}")
        assert r3.status_code == 200
        detail = r3.json()
        assert detail["plan"]["direction"] == "long"
        assert detail["backtest"]["sample_quality"] == "moderate"
        assert "NVDA" in detail["report_markdown"]

        # HTML
        r4 = client.get(f"/research/reports/{report_id}/html")
        assert r4.status_code == 200
        assert r4.headers["content-type"].startswith("text/html")
        assert "NVDA" in r4.text
