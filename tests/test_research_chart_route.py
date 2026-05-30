"""Tests for GET /research/reports/{id}/chart/{type}.png.

Uses FastAPI TestClient + in-memory SQLite. Seeds a single
ResearchReport row so the endpoint has a ticker + scan_date to work
with. ``fetch_shared_data`` is patched to return a deterministic
SharedData bundle (no network)."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database.connection import Base, get_db
from app.backend.database.models import ResearchReport
from app.backend.main import app
from src.research.shared_data import SharedData


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def db_session():
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
    yield Session
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def client(db_session):
    return TestClient(app)


@pytest.fixture
def seeded_report(db_session):
    """Insert one ResearchReport row and return its id."""
    s = db_session()
    try:
        row = ResearchReport(
            ticker="NVDA",
            scan_date=date.today().isoformat(),
            request_json={"ticker": "NVDA"},
            report_markdown="# NVDA",
            rendered_html="<html></html>",
            use_personas=False,
            user_id=1,
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return row.id
    finally:
        s.close()


def _fake_shared(ticker: str = "NVDA"):
    closes = [100.0 + i * 0.5 for i in range(200)]
    return SharedData(
        ticker=ticker,
        scan_date=date.today().isoformat(),
        prices=[{"close": c} for c in closes],
        financials=[], insider_trades=[], news=[], analyst_actions=[],
        analyst_targets=None, earnings_history=[], company_facts={},
        sector_etf_prices=[], spy_prices=[],
    )


class TestChartEndpoint:
    @patch("app.backend.routes.research.fetch_shared_data")
    def test_kline_daily_returns_png(self, mock_fetch, client, seeded_report):
        mock_fetch.return_value = _fake_shared()
        resp = client.get(f"/research/reports/{seeded_report}/chart/kline-daily.png")
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"] == "image/png"
        assert resp.content.startswith(PNG_SIGNATURE)

    @patch("app.backend.routes.research.fetch_shared_data")
    def test_equity_curve_returns_png(self, mock_fetch, client, seeded_report):
        mock_fetch.return_value = _fake_shared()
        resp = client.get(f"/research/reports/{seeded_report}/chart/equity-curve.png")
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"] == "image/png"
        assert resp.content.startswith(PNG_SIGNATURE)

    def test_unknown_report_id_returns_404(self, client):
        resp = client.get("/research/reports/99999/chart/kline-daily.png")
        assert resp.status_code == 404

    def test_unknown_chart_type_returns_404(self, client, seeded_report):
        resp = client.get(f"/research/reports/{seeded_report}/chart/garbage.png")
        assert resp.status_code == 404
