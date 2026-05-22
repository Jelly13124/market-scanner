"""HTTP route tests using FastAPI TestClient with an in-memory SQLite
DB and mocked run_research (no real LLM)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backend.database.connection import Base, get_db
from app.backend.database.models import ResearchReport, ResearchTradePlan
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

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


def _fake_state(ticker="NVDA"):
    return ResearchState(
        request=ResearchRequest(
            ticker=ticker, holding_status="watching",
            target_position_pct=0.05, risk_tolerance="moderate",
            report_goal="new_entry", use_personas=False,
            scanner_context=None,
        ),
        persona_assignments=None,
        module_results={},
        report_markdown="# Report",
        strategy=TradePlan(
            direction="long", entry_price=145.0, target_price=165.0,
            stop_price=138.0, horizon_days=30, sizing_pct=0.05,
            confidence=72, rationale="r",
        ),
        backtest_summary=BacktestSummary(
            matches_found=5, win_rate=0.6, avg_pnl_pct=0.08,
            max_drawdown_pct=-0.10, avg_holding_days=20.0,
            sample_quality="moderate", caveat=None,
        ),
        rendered_html="<html><body>NVDA</body></html>",
    )


class TestPostRun:
    @patch("app.backend.routes.research.run_research")
    @patch("app.backend.routes.research.render_html")
    def test_happy_path_returns_detail(self, mock_render, mock_run, client):
        mock_run.return_value = _fake_state("NVDA")
        mock_render.return_value = "<html><body>NVDA</body></html>"
        resp = client.post("/research/run", json={"ticker": "NVDA"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ticker"] == "NVDA"
        assert body["plan"]["direction"] == "long"
        assert body["backtest"]["sample_quality"] == "moderate"
        assert "id" in body

    @patch("app.backend.routes.research.run_research")
    @patch("app.backend.routes.research.render_html")
    def test_persists_report_and_plan(self, mock_render, mock_run, client):
        mock_run.return_value = _fake_state("NVDA")
        mock_render.return_value = "<html></html>"
        r1 = client.post("/research/run", json={"ticker": "NVDA"})
        report_id = r1.json()["id"]
        r2 = client.get(f"/research/reports/{report_id}")
        assert r2.status_code == 200
        assert r2.json()["ticker"] == "NVDA"


class TestListReports:
    @patch("app.backend.routes.research.run_research")
    @patch("app.backend.routes.research.render_html")
    def test_list_filters_by_ticker(self, mock_render, mock_run, client):
        mock_render.return_value = "<html></html>"
        mock_run.side_effect = lambda req: _fake_state(req.ticker)
        client.post("/research/run", json={"ticker": "NVDA"})
        client.post("/research/run", json={"ticker": "AVGO"})
        resp = client.get("/research/reports", params={"ticker": "NVDA"})
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["ticker"] == "NVDA"

    def test_list_empty_returns_empty_array(self, client):
        resp = client.get("/research/reports")
        assert resp.status_code == 200
        assert resp.json() == []


class TestGetHtml:
    @patch("app.backend.routes.research.run_research")
    @patch("app.backend.routes.research.render_html")
    def test_returns_html_with_correct_content_type(self, mock_render, mock_run, client):
        mock_run.return_value = _fake_state("NVDA")
        mock_render.return_value = "<html><body>NVDA report body</body></html>"
        r1 = client.post("/research/run", json={"ticker": "NVDA"})
        report_id = r1.json()["id"]
        r2 = client.get(f"/research/reports/{report_id}/html")
        assert r2.status_code == 200
        assert r2.headers["content-type"].startswith("text/html")
        assert "NVDA report body" in r2.text

    def test_html_404_for_missing_report(self, client):
        resp = client.get("/research/reports/99999/html")
        assert resp.status_code == 404


class TestGetDetail404:
    def test_returns_404(self, client):
        resp = client.get("/research/reports/99999")
        assert resp.status_code == 404
