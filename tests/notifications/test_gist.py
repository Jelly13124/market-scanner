"""gist.py — LLM-driven per-ticker take generation.

We mock the LLM at the ``get_model`` boundary so tests run without API
keys or network. The contract under test is:
  * One LLM call per ticker (call isolation)
  * Per-ticker failure doesn't kill other tickers
  * Trimming applied when LLM returns too-long output
  * Empty / missing-model paths return {} silently
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.backend.services.notifications.gist import (
    _GIST_CHAR_CAP,
    _top_analyst_signals,
    generate_gists,
)


def _run(tickers: list[str] | None = None, signals: dict | None = None):
    """Build a fake PipelineRun-shaped object."""
    decisions = {t: {"action": "buy", "quantity": 1, "confidence": 80,
                     "reasoning": f"because {t}"} for t in (tickers or [])}
    return SimpleNamespace(
        id="abc", scan_date="2026-05-19", template="quick",
        agent_decisions_json=decisions,
        analyst_signals_json=signals or {},
    )


def _structured_returns(per_ticker_gist: dict[str, str | Exception]):
    """Build a fake ``get_model`` return that, depending on how many
    times ``invoke`` is called, returns the next prepared gist (or
    raises if the prepared value is an Exception)."""
    iterator = iter(per_ticker_gist.values())

    def _invoke(_prompt):
        v = next(iterator)
        if isinstance(v, Exception):
            raise v
        return SimpleNamespace(gist=v)

    structured = MagicMock()
    structured.invoke.side_effect = _invoke
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


class TestGenerateGists:
    def test_empty_run_returns_empty_dict(self):
        run = _run(tickers=[])
        out = generate_gists(run, model_name="x", model_provider="y")
        assert out == {}

    def test_one_ticker_happy_path(self):
        run = _run(tickers=["AAPL"])
        llm = _structured_returns({"AAPL": "强势突破，做多合理"})
        with patch("src.llm.models.get_model", return_value=llm):
            out = generate_gists(run, model_name="x", model_provider="y")
        assert out == {"AAPL": "强势突破，做多合理"}

    def test_multiple_tickers_all_succeed(self):
        run = _run(tickers=["AAPL", "MSFT", "NVDA"])
        llm = _structured_returns({
            "AAPL": "理由 A", "MSFT": "理由 M", "NVDA": "理由 N",
        })
        with patch("src.llm.models.get_model", return_value=llm):
            out = generate_gists(run, model_name="x", model_provider="y")
        assert out == {"AAPL": "理由 A", "MSFT": "理由 M", "NVDA": "理由 N"}

    def test_per_ticker_failure_isolated(self):
        run = _run(tickers=["AAPL", "MSFT", "NVDA"])
        # MSFT's LLM call raises — AAPL + NVDA should still complete.
        llm = _structured_returns({
            "AAPL": "OK A",
            "MSFT": RuntimeError("rate limit"),
            "NVDA": "OK N",
        })
        with patch("src.llm.models.get_model", return_value=llm):
            out = generate_gists(run, model_name="x", model_provider="y")
        assert "AAPL" in out
        assert "NVDA" in out
        assert "MSFT" not in out

    def test_empty_gist_dropped(self):
        run = _run(tickers=["AAPL"])
        # LLM returned empty string — treat as failure, skip this ticker.
        llm = _structured_returns({"AAPL": "   "})
        with patch("src.llm.models.get_model", return_value=llm):
            out = generate_gists(run, model_name="x", model_provider="y")
        assert out == {}

    def test_long_gist_truncated(self):
        run = _run(tickers=["AAPL"])
        long_gist = "字" * (_GIST_CHAR_CAP + 20)  # over the cap
        llm = _structured_returns({"AAPL": long_gist})
        with patch("src.llm.models.get_model", return_value=llm):
            out = generate_gists(run, model_name="x", model_provider="y")
        # Truncated, suffix added.
        assert out["AAPL"].endswith("…")
        assert len(out["AAPL"]) <= _GIST_CHAR_CAP + 1  # +1 for the ellipsis

    def test_get_model_returns_none_means_skip(self):
        run = _run(tickers=["AAPL"])
        with patch("src.llm.models.get_model", return_value=None):
            out = generate_gists(run, model_name="x", model_provider="y")
        assert out == {}


class TestTopAnalystSignals:
    def test_returns_top_k_by_confidence(self):
        signals = {
            "fundamentals_analyst_agent": {
                "AAPL": {"signal": "bullish", "confidence": 60}
            },
            "warren_buffett_agent": {
                "AAPL": {"signal": "neutral", "confidence": 85}
            },
            "valuation_analyst_agent": {
                "AAPL": {"signal": "bearish", "confidence": 90}
            },
        }
        top = _top_analyst_signals(signals, "AAPL", k=2)
        keys = [k for k, _ in top]
        assert keys == ["valuation_analyst_agent", "warren_buffett_agent"]

    def test_missing_ticker_returns_empty(self):
        signals = {"fundamentals_analyst_agent": {"AAPL": {"signal": "bullish"}}}
        assert _top_analyst_signals(signals, "MSFT", k=2) == []

    def test_non_numeric_confidence_sorts_last(self):
        signals = {
            "a_agent": {"X": {"signal": "bullish", "confidence": None}},
            "b_agent": {"X": {"signal": "bearish", "confidence": 50}},
        }
        top = _top_analyst_signals(signals, "X", k=2)
        # The numeric-conf one should rank first.
        assert top[0][0] == "b_agent"
