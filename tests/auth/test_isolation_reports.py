"""Tenant-isolation tests for /research/reports.

User A creates a report; user B cannot list, get, or delete it (404/absent).
User A can retrieve and delete their own report.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tests.auth.conftest import auth_header


# ---------------------------------------------------------------------------
# Fake pipeline helpers (no real LLM)
# ---------------------------------------------------------------------------


def _fake_state(ticker="AAPL"):
    from src.research.models import (
        BacktestSummary, ResearchRequest, ResearchState, TradePlan,
    )
    return ResearchState(
        request=ResearchRequest(
            ticker=ticker, holding_status="watching",
            target_position_pct=0.05, risk_tolerance="moderate",
            report_goal="new_entry", use_personas=False,
            scanner_context=None,
        ),
        persona_assignments=None,
        module_results={},
        report_markdown=f"# {ticker} report",
        strategy=TradePlan(
            direction="long", entry_price=100.0, target_price=120.0,
            stop_price=90.0, horizon_days=30, sizing_pct=0.05,
            confidence=70, rationale="test",
        ),
        backtest_summary=BacktestSummary(
            matches_found=3, win_rate=0.6, avg_pnl_pct=0.05,
            max_drawdown_pct=-0.08, avg_holding_days=15.0,
            sample_quality="moderate", caveat=None,
        ),
        rendered_html=f"<html><body>{ticker}</body></html>",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _promote_superuser(full_client, email):
    """Promote a registered user to superuser in the test DB.

    The legacy ``POST /research/run`` (used here only to set up a report owned by
    A) is now superuser-only (it isn't wired for per-user keys). These tests check
    REPORT isolation, not the creation route, so we just need a report owned by A
    to exist; making A a superuser lets the legacy setup route through. B stays a
    normal user, so every isolation assertion (B can't see/delete A's report) is
    unchanged. (A cleaner future refactor: create reports via /research/analyze.)
    """
    from app.backend.database.models import User

    db = full_client.session_local()
    try:
        u = db.query(User).filter(User.email == email).first()
        u.is_superuser = True
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReportIsolation:
    @patch("app.backend.routes.research.render_html")
    @patch("app.backend.routes.research.run_research")
    def test_user_a_report_invisible_to_b_in_list(
        self, mock_run, mock_render, full_client, two_users,
    ):
        """B's list endpoint returns an empty array (no A's rows)."""
        tok_a, tok_b = two_users
        _promote_superuser(full_client, "a@x.com")
        mock_run.return_value = _fake_state("TSLA")
        mock_render.return_value = "<html></html>"

        r = full_client.post(
            "/research/run", json={"ticker": "TSLA"},
            headers=auth_header(tok_a),
        )
        assert r.status_code == 200, r.text

        # B lists reports — should be empty
        r2 = full_client.get("/research/reports", headers=auth_header(tok_b))
        assert r2.status_code == 200
        assert r2.json() == []

    @patch("app.backend.routes.research.render_html")
    @patch("app.backend.routes.research.run_research")
    def test_user_b_cannot_get_a_report(
        self, mock_run, mock_render, full_client, two_users,
    ):
        """GET /research/reports/{id} by B on A's report → 404."""
        tok_a, tok_b = two_users
        _promote_superuser(full_client, "a@x.com")
        mock_run.return_value = _fake_state("NVDA")
        mock_render.return_value = "<html></html>"

        r = full_client.post(
            "/research/run", json={"ticker": "NVDA"},
            headers=auth_header(tok_a),
        )
        report_id = r.json()["id"]

        r2 = full_client.get(
            f"/research/reports/{report_id}", headers=auth_header(tok_b),
        )
        assert r2.status_code == 404

    @patch("app.backend.routes.research.render_html")
    @patch("app.backend.routes.research.run_research")
    def test_user_b_cannot_delete_a_report(
        self, mock_run, mock_render, full_client, two_users,
    ):
        """DELETE /research/reports/{id} by B on A's report → 404."""
        tok_a, tok_b = two_users
        _promote_superuser(full_client, "a@x.com")
        mock_run.return_value = _fake_state("AAPL")
        mock_render.return_value = "<html></html>"

        r = full_client.post(
            "/research/run", json={"ticker": "AAPL"},
            headers=auth_header(tok_a),
        )
        report_id = r.json()["id"]

        r2 = full_client.delete(
            f"/research/reports/{report_id}", headers=auth_header(tok_b),
        )
        assert r2.status_code == 404

        # Report still exists for A
        r3 = full_client.get(
            f"/research/reports/{report_id}", headers=auth_header(tok_a),
        )
        assert r3.status_code == 200

    @patch("app.backend.routes.research.render_html")
    @patch("app.backend.routes.research.run_research")
    def test_user_a_can_delete_own_report(
        self, mock_run, mock_render, full_client, two_users,
    ):
        """A can delete their own report; subsequent GET returns 404."""
        tok_a, _ = two_users
        _promote_superuser(full_client, "a@x.com")
        mock_run.return_value = _fake_state("AVGO")
        mock_render.return_value = "<html></html>"

        r = full_client.post(
            "/research/run", json={"ticker": "AVGO"},
            headers=auth_header(tok_a),
        )
        report_id = r.json()["id"]

        r2 = full_client.delete(
            f"/research/reports/{report_id}", headers=auth_header(tok_a),
        )
        assert r2.status_code == 204

        r3 = full_client.get(
            f"/research/reports/{report_id}", headers=auth_header(tok_a),
        )
        assert r3.status_code == 404
