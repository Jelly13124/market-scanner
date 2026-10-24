"""Risk-position module: takes request.target_position_pct + risk_tolerance
+ outputs from technical (S/R) and valuation (fair value) to suggest
a stop/target ladder. Pure deterministic math + LLM rationale."""

from __future__ import annotations

from unittest.mock import patch

from src.research.modules.risk_position import RiskPositionModule
from src.research.models import ResearchRequest, ModuleResult
from src.research.shared_data import SharedData


def _req(risk="moderate", pos=0.05):
    return ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=pos, risk_tolerance=risk,
        report_goal="new_entry", use_personas=False, scanner_context=None,
    )


def _shared():
    return SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[],
        news=[], analyst_actions=[], analyst_targets=None,
        earnings_history=[], company_facts={},
        sector_etf_prices=[], spy_prices=[],
    )


def _prior():
    """Prior module outputs that risk_position consumes."""
    return {
        "valuation": ModuleResult(
            module_name="valuation", persona_used=None, markdown="",
            key_metrics={"current_price": 145.0, "fair_value_low": 150.0,
                         "fair_value_high": 180.0},
        ),
        "technical": ModuleResult(
            module_name="technical", persona_used=None, markdown="",
            key_metrics={"current_price": 145.0, "support": 138.0,
                         "resistance": 160.0, "sma_50": 142.0},
        ),
    }


class TestRiskPositionModule:
    def test_name(self):
        assert RiskPositionModule().name == "risk_position"

    @patch("src.research.modules.risk_position.call_research_llm")
    def test_conservative_tighter_than_aggressive(self, mock_llm):
        from src.research.modules.risk_position import _RiskNarrative
        mock_llm.return_value = _RiskNarrative(narrative="Plan ok.")

        cons = RiskPositionModule().run(_req(risk="conservative"), None, _shared(),
                                         prior_results=_prior())
        aggr = RiskPositionModule().run(_req(risk="aggressive"), None, _shared(),
                                         prior_results=_prior())
        assert cons.key_metrics["stop_price"] > aggr.key_metrics["stop_price"]
        assert cons.key_metrics["target_price"] < aggr.key_metrics["target_price"]

    def test_skipped_when_prior_missing(self):
        out = RiskPositionModule().run(_req(), None, _shared(), prior_results={})
        assert out.skipped is True


class TestRiskPositionPersonaPath:
    @patch("src.research.modules.risk_position.call_research_llm")
    def test_druckenmiller_persona_recorded(self, mock_llm):
        from src.research.modules.risk_position import _RiskNarrative
        captured = {}
        def _capture(prompt, model, **kw):
            captured["prompt"] = prompt
            return _RiskNarrative(narrative="Macro-aware plan.")
        mock_llm.side_effect = _capture
        out = RiskPositionModule().run(
            _req(), "druckenmiller", _shared(), prior_results=_prior(),
        )
        assert out.persona_used == "druckenmiller"
        assert any(kw in captured["prompt"].lower()
                   for kw in ("druckenmiller", "macro", "asymmetric"))

    @patch("src.research.modules.risk_position.call_research_llm")
    def test_unsupported_persona_coerced_to_none(self, mock_llm):
        from src.research.modules.risk_position import _RiskNarrative
        mock_llm.return_value = _RiskNarrative(narrative="objective.")
        # Wood is NOT in risk_position.supports_personas
        out = RiskPositionModule().run(
            _req(), "wood", _shared(), prior_results=_prior(),
        )
        assert out.persona_used is None
