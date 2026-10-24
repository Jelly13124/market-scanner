"""persona-router: one LLM call returns {module_name: persona_name | list | None}
based on ticker profile + scanner_context."""

from __future__ import annotations

from unittest.mock import patch

from src.research.router import route_personas, _RouterOutput
from src.research.shared_data import SharedData
from src.research.models import ResearchRequest


def _req():
    return ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal="new_entry", use_personas=True,
        scanner_context={"triggered_detectors": ["earnings_event"]},
    )


def _shared():
    return SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[],
        news=[], analyst_actions=[], analyst_targets=None,
        earnings_history=[],
        company_facts={"sector": "Technology", "market_cap": 3.0e12,
                       "weighted_average_shares": 24e9},
        sector_etf_prices=[], spy_prices=[],
    )


class TestRoutePersonas:
    @patch("src.research.router.call_research_llm")
    def test_returns_assignments_dict(self, mock_llm):
        mock_llm.return_value = _RouterOutput(
            fundamentals="munger",
            valuation="wood",
            risk_position="druckenmiller",
            debate=["wood", "burry"],
            rationale="Tech growth name; valuation tension between innovation premium and FCF reality.",
        )
        assignments = route_personas(_req(), _shared())
        assert assignments["fundamentals"] == "munger"
        assert assignments["valuation"] == "wood"
        assert assignments["risk_position"] == "druckenmiller"
        assert assignments["debate"] == ["wood", "burry"]

    @patch("src.research.router.call_research_llm")
    def test_invalid_persona_coerced_to_none(self, mock_llm):
        """Router LLM may hallucinate a persona name. Validator coerces
        unknown names to None for that module."""
        mock_llm.return_value = _RouterOutput(
            fundamentals="hallucinated",  # not in PERSONA_REGISTRY
            valuation="buffett",
            risk_position=None,
            debate=[],
            rationale="x",
        )
        assignments = route_personas(_req(), _shared())
        assert assignments["fundamentals"] is None
        assert assignments["valuation"] == "buffett"
        assert assignments["risk_position"] is None
        assert assignments["debate"] == []

    @patch("src.research.router.call_research_llm")
    def test_debate_requires_exactly_two(self, mock_llm):
        """Debate slot only fires with exactly 2 personas; 1 or 3+ -> empty."""
        mock_llm.return_value = _RouterOutput(
            fundamentals=None, valuation=None, risk_position=None,
            debate=["buffett"],  # only 1 -> reject
            rationale="x",
        )
        assignments = route_personas(_req(), _shared())
        assert assignments["debate"] == []

    @patch("src.research.router.call_research_llm")
    def test_debate_personas_must_be_valid(self, mock_llm):
        """Both debate personas must be in registry; any invalid -> empty."""
        mock_llm.return_value = _RouterOutput(
            fundamentals=None, valuation=None, risk_position=None,
            debate=["wood", "hallucinated"],
            rationale="x",
        )
        assignments = route_personas(_req(), _shared())
        assert assignments["debate"] == []
