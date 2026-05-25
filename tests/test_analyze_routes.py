"""POST /research/analyze tests with mocked run_sop + render_sop."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker

from app.backend.database.connection import Base, get_db
from app.backend.main import app
from src.research.models import (
    AnalyzeRequest, AnalyzeReport, BacktestVerdict, SectionPayload,
    SECTION_ORDER,
)


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def _override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


def _fake_report(ticker="NVDA"):
    req = AnalyzeRequest(
        ticker=ticker, objective="medium_term",
        position_budget_usd=10000, already_holds=False, cost_basis_usd=None,
        risk_tolerance="balanced", use_personas=True,
    )
    sections = {
        n: SectionPayload(
            name=n, markdown=f"## {n}\n\nbody for {n}",
            structured=None, skipped=False, persona_used=None,
        )
        for n in SECTION_ORDER
    }
    return AnalyzeReport(
        request=req, sections=sections,
        persona_assignments={"fundamentals": "buffett",
                             "valuation": "graham",
                             "risk_position": None,
                             "debate": ["wood", "burry"],
                             "_rationale": "x"},
        backtest=BacktestVerdict(
            signal="rsi_oversold", window_start="2020-01-01",
            window_end="2026-05-22", n_signals=10, win_rate_20d=0.6,
            avg_return_20d=0.02, t_stat=2.1, significant=True,
            verdict="significant",
        ),
        rendered_html=None,
    )


class TestAnalyzeEndpoint:
    @patch("app.backend.routes.research.run_sop")
    @patch("app.backend.routes.research.render_sop")
    def test_happy_path(self, mock_render, mock_run, client):
        mock_run.return_value = _fake_report("NVDA")
        mock_render.return_value = "<html><body>NVDA report</body></html>"
        resp = client.post("/research/analyze", json={
            "ticker": "nvda",  # lowercased — schema should uppercase
            "objective": "medium_term",
            "position_budget_usd": 10000,
            "risk_tolerance": "balanced",
            "use_personas": True,
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ticker"] == "NVDA"
        assert body["objective"] == "medium_term"
        assert body["use_personas"] is True
        assert "data_health" in body["sections"]
        assert body["sections"]["data_health"]["name"] == "data_health"
        assert body["backtest"]["signal"] == "rsi_oversold"
        assert body["persona_assignments"]["fundamentals"] == "buffett"

    @patch("app.backend.routes.research.run_sop")
    @patch("app.backend.routes.research.render_sop")
    def test_minimal_request(self, mock_render, mock_run, client):
        """Just ticker is enough — other fields default."""
        mock_run.return_value = _fake_report("AAPL")
        mock_render.return_value = "<html></html>"
        resp = client.post("/research/analyze", json={"ticker": "AAPL"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["objective"] == "general_research"
        assert body["risk_tolerance"] == "balanced"
        assert body["use_personas"] is False

    @patch("app.backend.routes.research.run_sop")
    @patch("app.backend.routes.research.render_sop")
    def test_persists_to_db(self, mock_render, mock_run, client):
        from app.backend.repositories.research_repository import (
            ResearchReportRepository)
        mock_run.return_value = _fake_report("NVDA")
        mock_render.return_value = "<html>x</html>"
        resp = client.post("/research/analyze", json={"ticker": "NVDA"})
        report_id = resp.json()["id"]
        # Fetch via existing Phase 3 endpoint to confirm it's there
        r2 = client.get(f"/research/reports/{report_id}/html")
        assert r2.status_code == 200
        assert "<html>x</html>" in r2.text

    @patch("app.backend.routes.research.run_sop")
    @patch("app.backend.routes.research.render_sop")
    def test_debate_rounds_round_trips(self, mock_render, mock_run, client):
        """Phase 5E — debate_rounds=4 should flow into the AnalyzeRequest
        handed to run_sop."""
        mock_run.return_value = _fake_report("NVDA")
        mock_render.return_value = "<html></html>"
        resp = client.post("/research/analyze", json={
            "ticker": "NVDA",
            "debate_rounds": 4,
        })
        assert resp.status_code == 200, resp.text
        # run_sop was called with the internal AnalyzeRequest
        called_with = mock_run.call_args[0][0]
        assert called_with.debate_rounds == 4

    @patch("app.backend.routes.research.run_sop")
    @patch("app.backend.routes.research.render_sop")
    def test_debate_rounds_defaults_to_three(self, mock_render, mock_run, client):
        """When the field is omitted, backend defaults to 3."""
        mock_run.return_value = _fake_report("NVDA")
        mock_render.return_value = "<html></html>"
        resp = client.post("/research/analyze", json={"ticker": "NVDA"})
        assert resp.status_code == 200, resp.text
        called_with = mock_run.call_args[0][0]
        assert called_with.debate_rounds == 3

    @patch("app.backend.routes.research.run_sop")
    @patch("app.backend.routes.research.render_sop")
    def test_debate_rounds_rejects_out_of_range(self, mock_render, mock_run, client):
        """Pydantic must reject values outside 1..5."""
        mock_run.return_value = _fake_report("NVDA")
        mock_render.return_value = "<html></html>"
        for bad in (0, 6, -1, 100):
            resp = client.post("/research/analyze", json={
                "ticker": "NVDA", "debate_rounds": bad,
            })
            assert resp.status_code == 422, f"expected 422 for {bad}, got {resp.status_code}"
