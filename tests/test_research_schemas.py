"""Pydantic schema validation for the research REST API."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.backend.models.research_schemas import (
    ResearchRunRequest,
    ResearchReportSummary,
    ResearchReportDetail,
    TradePlanPayload,
    BacktestSummaryPayload,
)


class TestResearchRunRequest:
    def test_minimal_request(self):
        r = ResearchRunRequest(ticker="NVDA")
        assert r.ticker == "NVDA"
        assert r.holding_status == "watching"
        assert r.target_position_pct == 0.05
        assert r.risk_tolerance == "moderate"
        assert r.report_goal == "general_research"
        assert r.use_personas is False

    def test_full_request(self):
        r = ResearchRunRequest(
            ticker="META",
            holding_status="holding",
            target_position_pct=0.10,
            risk_tolerance="aggressive",
            report_goal="hold_review",
            use_personas=True,
        )
        assert r.holding_status == "holding"

    def test_invalid_risk_rejected(self):
        with pytest.raises(ValidationError):
            ResearchRunRequest(ticker="NVDA", risk_tolerance="reckless")

    def test_invalid_position_pct_rejected(self):
        with pytest.raises(ValidationError):
            ResearchRunRequest(ticker="NVDA", target_position_pct=1.5)
        with pytest.raises(ValidationError):
            ResearchRunRequest(ticker="NVDA", target_position_pct=-0.01)

    def test_ticker_uppercased(self):
        r = ResearchRunRequest(ticker="nvda")
        assert r.ticker == "NVDA"


class TestTradePlanPayload:
    def test_long_plan(self):
        p = TradePlanPayload(
            direction="long", entry_price=145.0, target_price=165.0,
            stop_price=138.0, horizon_days=30, sizing_pct=0.05,
            confidence=72, rationale="test",
        )
        assert p.direction == "long"

    def test_stand_aside_allows_null_prices(self):
        p = TradePlanPayload(
            direction="stand_aside",
            entry_price=None, target_price=None, stop_price=None,
            horizon_days=0, sizing_pct=0.0, confidence=0, rationale="x",
        )
        assert p.entry_price is None

    def test_confidence_range_enforced(self):
        with pytest.raises(ValidationError):
            TradePlanPayload(
                direction="long", entry_price=1.0, target_price=2.0,
                stop_price=0.5, horizon_days=1, sizing_pct=0.01,
                confidence=150, rationale="x",
            )


class TestBacktestSummaryPayload:
    def test_strong_sample(self):
        b = BacktestSummaryPayload(
            matches_found=15, win_rate=0.6, avg_pnl_pct=0.08,
            max_drawdown_pct=-0.12, avg_holding_days=18.5,
            sample_quality="strong", caveat=None,
        )
        assert b.sample_quality == "strong"


class TestResearchReportSummary:
    def test_built_from_orm_row(self):
        """ResearchReportSummary should validate from an object with the
        expected attributes (ORM-mode)."""
        from types import SimpleNamespace
        from datetime import datetime
        row = SimpleNamespace(
            id=1, ticker="NVDA", scan_date="2026-05-22",
            created_at=datetime(2026, 5, 22, 16, 35),
            use_personas=True,
            duration_seconds=42.5,
        )
        s = ResearchReportSummary.model_validate(row, from_attributes=True)
        assert s.id == 1
        assert s.ticker == "NVDA"
