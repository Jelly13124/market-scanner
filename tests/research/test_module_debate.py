"""Debate module: simulate a two-round transcript between two router-picked
personas. Single LLM call producing the full transcript."""

from __future__ import annotations

from unittest.mock import patch

from src.research.models import ResearchRequest, ModuleResult
from src.research.modules.debate import run_debate, _DebateTranscript
from src.research.shared_data import SharedData


def _req():
    return ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal="new_entry", use_personas=True, scanner_context=None,
    )


def _shared():
    return SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[],
        news=[], analyst_actions=[], analyst_targets=None,
        earnings_history=[], company_facts={"sector": "Technology"},
        sector_etf_prices=[], spy_prices=[],
    )


class TestDebate:
    @patch("src.research.modules.debate.call_research_llm")
    def test_returns_module_result_with_transcript(self, mock_llm):
        mock_llm.return_value = _DebateTranscript(
            transcript=(
                "**Wood (Round 1):** ...\n\n"
                "**Burry (Round 1):** ...\n\n"
                "**Wood (Round 2):** ...\n\n"
                "**Burry (Round 2):** ..."
            ),
            verdict="Wood's growth thesis is more probable.",
        )
        out = run_debate(_req(), _shared(), ["wood", "burry"])
        assert isinstance(out, ModuleResult)
        assert out.module_name == "debate"
        assert "Wood" in out.markdown
        assert "Burry" in out.markdown
        assert out.skipped is False

    def test_skipped_when_not_two_personas(self):
        """Caller should ensure 2 personas — but defensive check too."""
        out = run_debate(_req(), _shared(), ["wood"])
        assert out.skipped is True

    def test_skipped_when_invalid_personas(self):
        out = run_debate(_req(), _shared(), ["wood", "hallucinated"])
        assert out.skipped is True

    @patch("src.research.modules.debate.call_research_llm")
    def test_prompt_contains_requested_rounds_count(self, mock_llm):
        """Phase 5E — the round count must be embedded in the LLM prompt."""
        mock_llm.return_value = _DebateTranscript(
            transcript="x", verdict="y",
        )
        run_debate(_req(), _shared(), ["wood", "burry"], debate_rounds=3)
        prompt = mock_llm.call_args[0][0]
        assert "3-round" in prompt, prompt
        # Round labels for 1, 2, 3 should be present in the round instructions.
        assert "Round 1:" in prompt
        assert "Round 2:" in prompt
        assert "Round 3:" in prompt
        assert "Round 4:" not in prompt

    @patch("src.research.modules.debate.call_research_llm")
    def test_rounds_clamped_to_5(self, mock_llm):
        mock_llm.return_value = _DebateTranscript(transcript="x", verdict="y")
        run_debate(_req(), _shared(), ["wood", "burry"], debate_rounds=99)
        prompt = mock_llm.call_args[0][0]
        assert "5-round" in prompt
        assert "Round 5:" in prompt
        assert "Round 6:" not in prompt

    @patch("src.research.modules.debate.call_research_llm")
    def test_rounds_clamped_to_1(self, mock_llm):
        mock_llm.return_value = _DebateTranscript(transcript="x", verdict="y")
        run_debate(_req(), _shared(), ["wood", "burry"], debate_rounds=0)
        prompt = mock_llm.call_args[0][0]
        assert "1-round" in prompt
        assert "Round 2:" not in prompt

    @patch("src.research.modules.debate.call_research_llm")
    def test_default_rounds_is_two_phase2_back_compat(self, mock_llm):
        """Legacy callers (Phase 2 pipeline) don't pass debate_rounds —
        the default must remain 2 to preserve current LLM prompt cost."""
        mock_llm.return_value = _DebateTranscript(transcript="x", verdict="y")
        run_debate(_req(), _shared(), ["wood", "burry"])
        prompt = mock_llm.call_args[0][0]
        assert "2-round" in prompt
        assert "Round 3:" not in prompt
