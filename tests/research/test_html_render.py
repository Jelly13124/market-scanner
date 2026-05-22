"""HTML render: ResearchState -> single self-contained HTML string.
Email-safe (inline styles, no external assets). Snapshot-style content
checks rather than DOM parsing - keeps the test fast and resilient to
template tweaks."""

from __future__ import annotations

from src.research.html_render import render_html
from src.research.models import (
    BacktestSummary, ModuleResult, ResearchRequest, ResearchState, TradePlan,
)


def _state(direction="long", use_personas=False, debate=False):
    request = ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal="new_entry", use_personas=use_personas, scanner_context=None,
    )
    module_results = {
        "macro": ModuleResult(
            module_name="macro", persona_used=None,
            markdown="SPY +5%, regime up.", key_metrics={},
        ),
        "valuation": ModuleResult(
            module_name="valuation",
            persona_used="buffett" if use_personas else None,
            markdown="Fair value $160.", key_metrics={},
        ),
    }
    if debate:
        module_results["debate"] = ModuleResult(
            module_name="debate", persona_used="wood+burry",
            markdown="**Wood:** growth. **Burry:** value.", key_metrics={},
        )
    persona_assignments = None
    if use_personas:
        persona_assignments = {
            "fundamentals": "buffett",
            "valuation": "buffett",
            "risk_position": None,
            "debate": ["wood", "burry"] if debate else [],
            "_rationale": "tech name; growth vs value.",
        }
    return ResearchState(
        request=request,
        persona_assignments=persona_assignments,
        module_results=module_results,
        report_markdown="# NVDA report\n\nNarrative goes here.",
        strategy=TradePlan(
            direction=direction,
            entry_price=145.0 if direction != "stand_aside" else None,
            target_price=165.0 if direction != "stand_aside" else None,
            stop_price=138.0 if direction != "stand_aside" else None,
            horizon_days=30 if direction != "stand_aside" else 0,
            sizing_pct=0.05 if direction != "stand_aside" else 0.0,
            confidence=72 if direction != "stand_aside" else 0,
            rationale="Earnings beat + insider cluster.",
        ),
        backtest_summary=BacktestSummary(
            matches_found=5, win_rate=0.6, avg_pnl_pct=0.08,
            max_drawdown_pct=-0.10, avg_holding_days=20.0,
            sample_quality="moderate", caveat=None,
        ),
        rendered_html=None,
    )


class TestRenderHtml:
    def test_returns_complete_html_document(self):
        html = render_html(_state())
        assert html.startswith("<!DOCTYPE html>") or html.lstrip().startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_ticker_in_title_or_header(self):
        html = render_html(_state())
        assert "NVDA" in html

    def test_trade_plan_box_rendered(self):
        html = render_html(_state(direction="long"))
        assert "Entry" in html
        assert "145" in html
        assert "Target" in html

    def test_stand_aside_renders_no_prices(self):
        html = render_html(_state(direction="stand_aside"))
        assert "stand" in html.lower()
        assert "$145" not in html

    def test_backtest_box_rendered(self):
        html = render_html(_state())
        assert "moderate" in html.lower() or "Moderate" in html
        assert "5" in html

    def test_report_markdown_included(self):
        html = render_html(_state())
        assert "Narrative goes here" in html

    def test_persona_section_only_when_personas_used(self):
        html_off = render_html(_state(use_personas=False))
        html_on = render_html(_state(use_personas=True))
        assert "buffett" not in html_off.lower()
        assert "buffett" in html_on.lower()

    def test_debate_section_when_present(self):
        html_no_debate = render_html(_state(use_personas=True, debate=False))
        html_debate = render_html(_state(use_personas=True, debate=True))
        assert "wood vs burry" in html_debate.lower() or "wood" in html_debate.lower()
        assert "wood vs burry" not in html_no_debate.lower()

    def test_html_escapes_ticker(self):
        """Defensive: ticker is user input, must be escaped."""
        state = _state()
        state["request"].ticker = "X<script>"
        html = render_html(state)
        assert "<script>" not in html  # raw script tag absent
        assert "&lt;script&gt;" in html  # single-escaped form present (NOT &amp;lt;)
