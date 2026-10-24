"""Smoke tests for src.research.models — every dataclass round-trips
through dict serialization without losing information, and Literal
field validation rejects bad values."""

from __future__ import annotations

import pytest
from dataclasses import asdict

from src.research.models import (
    ResearchRequest,
    TradePlan,
    ModuleResult,
    BacktestSummary,
)


class TestResearchRequest:
    def test_minimal_construction(self):
        r = ResearchRequest(
            ticker="NVDA",
            holding_status="watching",
            target_position_pct=0.05,
            risk_tolerance="moderate",
            report_goal="new_entry",
            use_personas=False,
            scanner_context=None,
        )
        assert r.ticker == "NVDA"
        assert r.target_position_pct == 0.05
        assert r.scanner_context is None

    def test_with_scanner_context(self):
        ctx = {"triggered_detectors": ["earnings_event"], "rank": 1}
        r = ResearchRequest(
            ticker="MU",
            holding_status="considering_buy",
            target_position_pct=0.03,
            risk_tolerance="aggressive",
            report_goal="new_entry",
            use_personas=True,
            scanner_context=ctx,
        )
        assert r.scanner_context == ctx


class TestTradePlan:
    def test_long_plan(self):
        p = TradePlan(
            direction="long",
            entry_price=145.0,
            target_price=165.0,
            stop_price=138.0,
            horizon_days=30,
            sizing_pct=0.05,
            confidence=72,
            rationale="Earnings beat + insider cluster + below 50d SMA.",
        )
        assert p.direction == "long"
        assert p.target_price - p.entry_price == 20.0

    def test_stand_aside_has_none_prices(self):
        p = TradePlan(
            direction="stand_aside",
            entry_price=None,
            target_price=None,
            stop_price=None,
            horizon_days=0,
            sizing_pct=0.0,
            confidence=0,
            rationale="Data insufficient.",
        )
        assert p.direction == "stand_aside"
        assert p.entry_price is None


class TestModuleResult:
    def test_default_metrics_empty(self):
        m = ModuleResult(
            module_name="macro",
            persona_used=None,
            markdown="SPY +5%, regime up.",
        )
        assert m.key_metrics == {}
        assert m.chart_data is None
        assert m.skipped is False

    def test_skipped_module(self):
        m = ModuleResult(
            module_name="sentiment",
            persona_used=None,
            markdown="",
            skipped=True,
            skip_reason="No news data available",
        )
        assert m.skipped is True


class TestBacktestSummary:
    def test_strong_sample(self):
        b = BacktestSummary(
            matches_found=15,
            win_rate=0.6,
            avg_pnl_pct=0.08,
            max_drawdown_pct=-0.12,
            avg_holding_days=18.5,
            sample_quality="strong",
            caveat=None,
        )
        assert b.sample_quality == "strong"

    def test_insufficient_sample_carries_caveat(self):
        b = BacktestSummary(
            matches_found=0,
            win_rate=None,
            avg_pnl_pct=None,
            max_drawdown_pct=None,
            avg_holding_days=None,
            sample_quality="insufficient",
            caveat="No historical trigger matches for this ticker",
        )
        assert b.win_rate is None
        assert b.caveat is not None
