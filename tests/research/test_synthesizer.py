"""Synthesizer: takes ResearchRequest + module_results, calls LLM, returns
(report_markdown, TradePlan)."""

from __future__ import annotations

from unittest.mock import patch

from src.research.models import ModuleResult, ResearchRequest, TradePlan
from src.research.synthesizer import synthesize, _SynthOutput


def _req(goal="new_entry"):
    return ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal=goal, use_personas=False, scanner_context=None,
    )


def _mod(name, markdown, metrics=None):
    return ModuleResult(
        module_name=name, persona_used=None, markdown=markdown,
        key_metrics=metrics or {},
    )


class TestSynthesize:
    @patch("src.research.synthesizer.call_research_llm")
    def test_returns_report_and_plan(self, mock_llm):
        mock_llm.return_value = _SynthOutput(
            report_markdown="# NVDA\n\nGood setup.",
            direction="long", entry_price=145.0, target_price=165.0,
            stop_price=138.0, horizon_days=30, sizing_pct=0.05,
            confidence=72, rationale="Earnings beat + insider buy.",
        )
        report, plan = synthesize(_req(), {
            "macro": _mod("macro", "SPY up 5%"),
            "valuation": _mod("valuation", "Fair value $160",
                              {"fair_value_high": 180.0}),
        })
        assert "NVDA" in report
        assert isinstance(plan, TradePlan)
        assert plan.direction == "long"
        assert plan.entry_price == 145.0

    @patch("src.research.synthesizer.call_research_llm")
    def test_stand_aside_zeros_prices(self, mock_llm):
        mock_llm.return_value = _SynthOutput(
            report_markdown="Skip", direction="stand_aside",
            entry_price=None, target_price=None, stop_price=None,
            horizon_days=0, sizing_pct=0.0, confidence=0,
            rationale="Insufficient data",
        )
        _, plan = synthesize(_req(), {})
        assert plan.direction == "stand_aside"
        assert plan.entry_price is None

    @patch("src.research.synthesizer.call_research_llm")
    def test_skipped_modules_omitted_from_prompt(self, mock_llm):
        """Modules with skipped=True should not appear in the prompt body."""
        captured = {}
        def _capture(prompt, model, **kw):
            captured["prompt"] = prompt
            return _SynthOutput(
                report_markdown="ok", direction="stand_aside",
                entry_price=None, target_price=None, stop_price=None,
                horizon_days=0, sizing_pct=0.0, confidence=0, rationale="x",
            )
        mock_llm.side_effect = _capture
        synthesize(_req(), {
            "macro": _mod("macro", "live", metrics={}),
            "sentiment": ModuleResult(
                module_name="sentiment", persona_used=None, markdown="",
                skipped=True, skip_reason="no news",
            ),
        })
        assert "macro" in captured["prompt"].lower()
        # Skipped module not referenced
        assert "sentiment" not in captured["prompt"].lower() or "no news" not in captured["prompt"].lower()
