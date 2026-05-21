"""Tests for the v2 scanner→agent bridge node."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from src.agents.scanner_signal import (
    _detector_bullets,
    _fallback_reasoning,
    _format_components,
    _ScannerReasoning,
    scanner_signal_agent,
)


def _state(
    *,
    tickers: list[str],
    scanner_context: dict[str, dict] | None = None,
    show_reasoning: bool = False,
) -> dict:
    """Build the minimal AgentState shape the node consumes."""
    return {
        "messages": [],
        "data": {
            "tickers": tickers,
            "scanner_context": scanner_context or {},
            "analyst_signals": {},
            "end_date": "2026-05-18",
        },
        "metadata": {
            "show_reasoning": show_reasoning,
            "model_name": "gpt-4.1",
            "model_provider": "OpenAI",
        },
    }


# Stub the LLM so tests don't hit the network. Returns a fixed reasoning string
# that we can assert on. Override with a different patch in specific tests
# that need to inspect the prompt or simulate failure.
def _stub_call_llm(return_text: str = "stubbed reasoning"):
    def _impl(prompt, pydantic_model, agent_name=None, state=None,
              max_retries=3, default_factory=None):
        return pydantic_model(reasoning=return_text)
    return _impl


# ---------------------------------------------------------------------------
# _format_components
# ---------------------------------------------------------------------------


class TestFormatComponents:
    def test_empty_dict_returns_placeholder(self):
        assert _format_components({}) == "(no components)"

    def test_non_dict_returns_placeholder(self):
        assert _format_components("not a dict") == "(no components)"  # type: ignore[arg-type]

    def test_picks_top_n_by_absolute_value(self):
        # max_items=4 — biggest abs values win, regardless of sign
        comps = {"a": 0.1, "b": -2.5, "c": 1.7, "d": 0.5, "e": -3.0, "f": 0.01}
        out = _format_components(comps, max_items=4)
        # e, b, c, d should appear (by abs); a and f get folded into "+2 more"
        assert "e=-3" in out
        assert "b=-2.5" in out
        assert "c=+1.7" in out
        assert "d=+0.5" in out
        assert "+2 more" in out

    def test_ints_keep_int_formatting(self):
        out = _format_components({"phase": 2, "history_n": 4})
        assert "phase=2" in out
        assert "history_n=4" in out

    def test_skips_non_numeric(self):
        # Strings/None aren't picked
        out = _format_components({"phase": 2.0, "label": "BEAT", "z": 1.5})
        assert "label" not in out
        assert "phase" in out and "z" in out


# ---------------------------------------------------------------------------
# _detector_bullets
# ---------------------------------------------------------------------------


class TestDetectorBullets:
    def test_no_triggered_detectors(self):
        ctx = {"triggered_detectors": [], "triggered_components": {}}
        assert _detector_bullets(ctx) == "(no detectors fired)"

    def test_renders_severity_when_present(self):
        ctx = {
            "triggered_detectors": ["earnings_event"],
            "triggered_components": {
                "earnings_event": {"raw_z": 2.5, "phase": 2.0, "biz_days_to_event": 1.0},
            },
        }
        out = _detector_bullets(ctx)
        assert "earnings_event" in out
        assert "severity_z=+2.50" in out
        assert "phase" in out  # components rendered too

    def test_handles_missing_components_dict(self):
        ctx = {
            "triggered_detectors": ["intraday_move"],
            "triggered_components": {},  # detector fired but no components stored
        }
        out = _detector_bullets(ctx)
        assert "intraday_move" in out
        assert "(no components)" in out


# ---------------------------------------------------------------------------
# _fallback_reasoning
# ---------------------------------------------------------------------------


class TestFallbackReasoning:
    def test_empty_triggers(self):
        out = _fallback_reasoning({"composite_score": 0, "triggered_detectors": []})
        assert "no detectors" in out.lower()

    def test_with_triggers_names_them(self):
        ctx = {
            "composite_score": 87.5,
            "direction": "bullish",  # ignored by direction-free design
            "triggered_detectors": ["earnings_event", "obv_divergence"],
        }
        out = _fallback_reasoning(ctx)
        assert "earnings_event" in out
        assert "obv_divergence" in out
        # Per 2026-05-21 §6 finding, composite_score is anti-predictive at
        # rank level — it's been dropped from fallback (and from the LLM
        # prompt) so it can't bias downstream agents.
        assert "/100" not in out
        # Direction-free per 2026-05-19 redesign: fallback must NOT propagate
        # the bullish/bearish label, only that downstream analysts decide.
        assert "bullish" not in out
        assert "bearish" not in out
        assert "downstream" in out.lower()


# ---------------------------------------------------------------------------
# scanner_signal_agent — rule logic + writes
# ---------------------------------------------------------------------------


class TestScannerSignalAgent:
    @patch("src.agents.scanner_signal.call_llm", new_callable=lambda: _stub_call_llm("AAPL post-earnings drift."))
    def test_post_earnings_event_emits_neutral(self, _stub):
        """Even when the scanner labels direction=bullish, the bridge agent
        always outputs neutral so persona analysts derive direction from
        the event description without prior contamination."""
        ctx = {
            "AAPL": {
                "scan_date": "2024-08-02",
                "rank": 1,
                "composite_score": 87.5,
                "direction": "bullish",  # ignored by bridge
                "triggered_detectors": ["earnings_event"],
                "triggered_components": {
                    "earnings_event": {"phase": 2.0, "raw_z": 2.5, "surprise_pct": 0.045},
                },
            }
        }
        state = _state(tickers=["AAPL"], scanner_context=ctx)
        result = scanner_signal_agent(state)
        signals = state["data"]["analyst_signals"]["scanner_signal_agent"]
        assert signals["AAPL"]["signal"] == "neutral"           # always neutral
        assert signals["AAPL"]["confidence"] == 88              # round(87.5)
        assert signals["AAPL"]["reasoning"] == "AAPL post-earnings drift."
        msg_payload = json.loads(result["messages"][0].content)
        assert msg_payload["AAPL"]["signal"] == "neutral"

    @patch("src.agents.scanner_signal.call_llm", new_callable=lambda: _stub_call_llm("bearish desc"))
    def test_bearish_direction_in_context_still_emits_neutral(self, _stub):
        """Scanner direction=bearish must NOT propagate as signal."""
        ctx = {"TSLA": {"composite_score": 72, "direction": "bearish",
                        "triggered_detectors": ["earnings_event"],
                        "triggered_components": {}}}
        state = _state(tickers=["TSLA"], scanner_context=ctx)
        scanner_signal_agent(state)
        assert state["data"]["analyst_signals"]["scanner_signal_agent"]["TSLA"]["signal"] == "neutral"
        assert state["data"]["analyst_signals"]["scanner_signal_agent"]["TSLA"]["confidence"] == 72

    @patch("src.agents.scanner_signal.call_llm", new_callable=lambda: _stub_call_llm())
    def test_neutral_direction(self, _stub):
        ctx = {"MSFT": {"composite_score": 50, "direction": "neutral",
                        "triggered_detectors": ["bollinger_squeeze"],
                        "triggered_components": {"bollinger_squeeze": {"percentile": 0.05}}}}
        state = _state(tickers=["MSFT"], scanner_context=ctx)
        scanner_signal_agent(state)
        assert state["data"]["analyst_signals"]["scanner_signal_agent"]["MSFT"]["signal"] == "neutral"

    @patch("src.agents.scanner_signal.call_llm", new_callable=lambda: _stub_call_llm())
    def test_missing_ticker_abstains(self, _stub):
        # Ticker in workflow but NOT in scanner_context (e.g., user-added)
        state = _state(tickers=["AAPL", "NVDA"], scanner_context={
            "AAPL": {"composite_score": 80, "direction": "bullish",
                     "triggered_detectors": ["intraday_move"],
                     "triggered_components": {}}
        })
        scanner_signal_agent(state)
        signals = state["data"]["analyst_signals"]["scanner_signal_agent"]
        assert signals["NVDA"] == {
            "signal": "neutral",
            "confidence": 0,
            "reasoning": "Ticker not in today's scanner watchlist.",
        }
        # AAPL still gets its signal — direction-free, always neutral now.
        assert signals["AAPL"]["signal"] == "neutral"
        assert signals["AAPL"]["confidence"] == 80

    @patch("src.agents.scanner_signal.call_llm", new_callable=lambda: _stub_call_llm())
    def test_invalid_direction_coerced_neutral(self, _stub):
        ctx = {"AAPL": {"composite_score": 60, "direction": "WAT",
                        "triggered_detectors": [],
                        "triggered_components": {}}}
        state = _state(tickers=["AAPL"], scanner_context=ctx)
        scanner_signal_agent(state)
        assert state["data"]["analyst_signals"]["scanner_signal_agent"]["AAPL"]["signal"] == "neutral"

    @patch("src.agents.scanner_signal.call_llm", new_callable=lambda: _stub_call_llm())
    def test_score_edges_clip(self, _stub):
        ctx = {
            "A": {"composite_score": -10, "direction": "neutral",
                  "triggered_detectors": [], "triggered_components": {}},
            "B": {"composite_score": 150, "direction": "neutral",
                  "triggered_detectors": [], "triggered_components": {}},
            "C": {"composite_score": "not a number", "direction": "neutral",
                  "triggered_detectors": [], "triggered_components": {}},
        }
        state = _state(tickers=["A", "B", "C"], scanner_context=ctx)
        scanner_signal_agent(state)
        s = state["data"]["analyst_signals"]["scanner_signal_agent"]
        assert s["A"]["confidence"] == 0
        assert s["B"]["confidence"] == 100
        assert s["C"]["confidence"] == 0  # non-numeric → 0

    @patch("src.agents.scanner_signal.call_llm")
    def test_llm_default_factory_carries_fallback(self, mock_call_llm):
        # Simulate call_llm calling default_factory (which carries our
        # fallback string). Real call_llm does this on persistent failure.
        def _invoke_default(prompt, pydantic_model, agent_name=None, state=None,
                            max_retries=3, default_factory=None):
            assert default_factory is not None
            return default_factory()
        mock_call_llm.side_effect = _invoke_default

        ctx = {"AAPL": {
            "scan_date": "2024-08-02", "rank": 1,
            "composite_score": 87.5, "direction": "bullish",
            "triggered_detectors": ["earnings_event", "obv_divergence"],
            "triggered_components": {},
        }}
        state = _state(tickers=["AAPL"], scanner_context=ctx)
        scanner_signal_agent(state)
        reasoning = state["data"]["analyst_signals"]["scanner_signal_agent"]["AAPL"]["reasoning"]
        # Direction-free fallback: detectors only, NO bullish/bearish, NO score.
        assert "earnings_event" in reasoning
        assert "obv_divergence" in reasoning
        assert "/100" not in reasoning
        assert "bullish" not in reasoning
        assert "bearish" not in reasoning

    @patch("src.agents.scanner_signal.call_llm")
    def test_prompt_contains_detector_context(self, mock_call_llm):
        # Capture the prompt to assert it carries the detector context
        # (this is what makes the LLM reasoning useful — not a generic prompt).
        captured = {}

        def _capture(prompt, pydantic_model, **kwargs):
            captured["prompt"] = prompt
            return pydantic_model(reasoning="ok")
        mock_call_llm.side_effect = _capture

        ctx = {"AAPL": {
            "scan_date": "2024-08-02", "rank": 3, "composite_score": 70.0,
            "direction": "bullish",
            "triggered_detectors": ["earnings_event"],
            "triggered_components": {
                "earnings_event": {"phase": 2.0, "raw_z": 2.8, "surprise_pct": 0.052},
            },
        }}
        state = _state(tickers=["AAPL"], scanner_context=ctx)
        scanner_signal_agent(state)

        # Check the HUMAN message specifically — the system message contains
        # the literal words "bullish/bearish" as an instruction NOT to use them,
        # which would false-positive a naive substring check.
        messages = captured["prompt"].to_messages()
        human_text = next(m.content for m in messages if m.type == "human")
        assert "AAPL" in human_text
        assert "earnings_event" in human_text
        assert "2024-08-02" in human_text
        # Direction-free input: scanner's directional LABEL must not be a
        # data field in the human message. (The word "directional" itself
        # may appear as a meta-explanation that the score is NOT directional;
        # that's fine — we only care that bullish/bearish aren't injected.)
        assert "bullish" not in human_text
        assert "bearish" not in human_text

    @patch("src.agents.scanner_signal.call_llm", new_callable=lambda: _stub_call_llm())
    def test_empty_tickers_writes_empty_signal_dict(self, _stub):
        state = _state(tickers=[], scanner_context={})
        scanner_signal_agent(state)
        assert state["data"]["analyst_signals"]["scanner_signal_agent"] == {}
