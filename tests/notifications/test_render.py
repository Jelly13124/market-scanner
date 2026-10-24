"""HTML + text rendering for notification emails.

We don't snapshot the full HTML — gmail rendering is wide and small
diffs in styling would be noise. We assert the structural contract:
ticker names, action labels, signal colors, and resilience to missing
data are all present.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.backend.services.notifications.render import (
    render_pipeline_html,
    render_pipeline_text,
)


def _fake_run(
    *,
    id: str = "abc123",
    scan_date: str = "2026-05-18",
    template: str = "balanced",
    duration: float | None = 73.0,
    decisions: dict | None = None,
    signals: dict | None = None,
):
    """Minimal duck-typed PipelineRun replacement for renderer tests."""
    return SimpleNamespace(
        id=id,
        scan_date=scan_date,
        template=template,
        duration_seconds=duration,
        agent_decisions_json=decisions if decisions is not None else {},
        analyst_signals_json=signals if signals is not None else {},
    )


class TestHtmlRenderer:
    def test_header_includes_metadata(self):
        run = _fake_run()
        out = render_pipeline_html(run)
        assert "2026-05-18" in out
        assert "balanced" in out
        assert "73.0s" in out

    def test_renders_per_ticker_sections(self):
        run = _fake_run(decisions={
            "AAPL": {"action": "buy", "quantity": 25, "confidence": 80,
                     "reasoning": "Bullish trend"},
            "TSLA": {"action": "short", "quantity": 100, "confidence": 90,
                     "reasoning": "Overvalued"},
        })
        out = render_pipeline_html(run)
        assert "AAPL" in out
        assert "TSLA" in out
        assert "buy" in out.lower()
        assert "short" in out.lower()
        # PM reasoning surfaces in the body.
        assert "Bullish trend" in out
        assert "Overvalued" in out

    def test_action_pill_color_distinguishes_buy_vs_short(self):
        buy_run = _fake_run(decisions={"X": {"action": "buy", "quantity": 1}})
        short_run = _fake_run(decisions={"X": {"action": "short", "quantity": 1}})
        # Green for buy, red for short — verify the actual color codes
        # the renderer emits.
        assert "#dcfce7" in render_pipeline_html(buy_run)  # green-100 bg
        assert "#fee2e2" in render_pipeline_html(short_run)  # red-100 bg

    def test_renders_per_analyst_signals(self):
        run = _fake_run(
            decisions={"AAPL": {"action": "buy", "quantity": 1}},
            signals={
                "fundamentals_analyst_agent": {
                    "AAPL": {"signal": "bullish", "confidence": 75,
                             "reasoning": "Strong ROE, low debt"},
                },
                "warren_buffett_agent": {
                    "AAPL": {"signal": "neutral", "confidence": 55,
                             "reasoning": {"summary": "Decent moat",
                                           "score": 7}},
                },
            },
        )
        out = render_pipeline_html(run)
        assert "fundamentals analyst" in out  # _agent suffix stripped
        assert "warren buffett" in out
        assert "Strong ROE, low debt" in out
        # Dict reasoning coerced — should pick `summary` key.
        assert "Decent moat" in out

    def test_empty_decisions_renders_friendly_message(self):
        run = _fake_run(decisions={})
        out = render_pipeline_html(run)
        assert "scanner didn't fire" in out.lower() or "no tickers" in out.lower()

    def test_resilient_to_missing_fields(self):
        # Decision with no reasoning, no confidence, no quantity.
        run = _fake_run(decisions={"AAPL": {"action": "hold"}})
        # Should not raise.
        out = render_pipeline_html(run)
        assert "AAPL" in out
        assert "hold" in out.lower()

    def test_resilient_to_missing_analyst_signal_for_ticker(self):
        run = _fake_run(
            decisions={"AAPL": {"action": "buy", "quantity": 1},
                       "TSLA": {"action": "buy", "quantity": 1}},
            signals={
                "fundamentals_analyst_agent": {
                    "AAPL": {"signal": "bullish", "confidence": 80}
                    # TSLA missing.
                },
            },
        )
        out = render_pipeline_html(run)
        # Both tickers render even though TSLA has no analyst rows.
        assert "AAPL" in out
        assert "TSLA" in out

    def test_truncates_long_reasoning(self):
        long_text = "x" * 500
        run = _fake_run(
            decisions={"X": {"action": "buy", "quantity": 1,
                             "reasoning": long_text}},
        )
        out = render_pipeline_html(run)
        # Truncated at 320 chars (per renderer) — never the full 500.
        assert "x" * 500 not in out
        assert "x" * 300 in out  # at least most of it
        assert "…" in out

    def test_html_escapes_user_data(self):
        run = _fake_run(
            decisions={"X": {"action": "buy", "quantity": 1,
                             "reasoning": "<script>alert(1)</script>"}},
        )
        out = render_pipeline_html(run)
        assert "<script>" not in out
        assert "&lt;script&gt;" in out

    def test_output_is_valid_html_skeleton(self):
        out = render_pipeline_html(_fake_run())
        assert out.startswith("<!doctype html>")
        assert "</html>" in out


class TestValuationConflict:
    """Red warning bar appears when PM action contradicts valuation signal."""

    def _run_with(self, action: str, val_signal: str):
        return _fake_run(
            decisions={"AAPL": {"action": action, "quantity": 10, "confidence": 80,
                                "reasoning": "x"}},
            signals={
                "valuation_analyst_agent": {
                    "AAPL": {"signal": val_signal, "confidence": 90},
                },
            },
        )

    def test_buy_vs_bearish_valuation_shows_warning(self):
        out = render_pipeline_html(self._run_with("buy", "bearish"))
        assert "PM 决策" in out and "矛盾" in out
        # Warning bar uses the red-100 background — verify the actual color.
        assert "#fee2e2" in out

    def test_short_vs_bullish_valuation_shows_warning(self):
        out = render_pipeline_html(self._run_with("short", "bullish"))
        assert "PM 决策" in out and "矛盾" in out

    def test_buy_vs_bullish_no_warning(self):
        out = render_pipeline_html(self._run_with("buy", "bullish"))
        assert "矛盾" not in out

    def test_short_vs_bearish_no_warning(self):
        out = render_pipeline_html(self._run_with("short", "bearish"))
        assert "矛盾" not in out

    def test_neutral_valuation_never_conflicts(self):
        out = render_pipeline_html(self._run_with("buy", "neutral"))
        assert "矛盾" not in out

    def test_hold_action_never_flagged(self):
        # HOLD has no directional conviction → no conflict regardless of valuation.
        out = render_pipeline_html(self._run_with("hold", "bearish"))
        assert "矛盾" not in out

    def test_missing_valuation_signal_does_not_crash(self):
        # No valuation_analyst_agent at all — should not raise.
        run = _fake_run(
            decisions={"AAPL": {"action": "buy", "quantity": 1}},
            signals={"fundamentals_analyst_agent": {
                "AAPL": {"signal": "bullish", "confidence": 70},
            }},
        )
        out = render_pipeline_html(run)
        assert "矛盾" not in out


class TestGistInjection:
    """gist_map renders as a yellow ' 💡 Take' row under PM action header."""

    def test_renders_gist_when_present(self):
        run = _fake_run(decisions={"AAPL": {"action": "buy", "quantity": 1, "confidence": 80}})
        out = render_pipeline_html(run, gist_map={"AAPL": "强势突破，估值合理"})
        assert "💡 Take" in out
        assert "强势突破，估值合理" in out
        # Yellow background — amber-100.
        assert "#fef3c7" in out

    def test_no_gist_when_map_is_none(self):
        run = _fake_run(decisions={"AAPL": {"action": "buy", "quantity": 1}})
        out = render_pipeline_html(run, gist_map=None)
        assert "💡 Take" not in out

    def test_partial_gist_map_renders_only_matching_tickers(self):
        run = _fake_run(decisions={
            "AAPL": {"action": "buy", "quantity": 1},
            "MSFT": {"action": "buy", "quantity": 1},
        })
        # Only AAPL has a gist; MSFT should render without the row.
        out = render_pipeline_html(run, gist_map={"AAPL": "理由 A"})
        assert "理由 A" in out
        # MSFT block exists but no second "💡 Take" row.
        assert out.count("💡 Take") == 1

    def test_gist_is_html_escaped(self):
        run = _fake_run(decisions={"X": {"action": "buy", "quantity": 1}})
        out = render_pipeline_html(run, gist_map={"X": "<script>x</script>"})
        assert "<script>" not in out
        assert "&lt;script&gt;" in out


class TestTextRenderer:
    def test_includes_ticker_and_action(self):
        run = _fake_run(decisions={
            "AAPL": {"action": "buy", "quantity": 25, "confidence": 80,
                     "reasoning": "Bullish trend"},
        })
        out = render_pipeline_text(run)
        assert "AAPL" in out
        assert "BUY" in out
        assert "qty=25" in out
        assert "conf=80" in out
        assert "Bullish trend" in out

    def test_empty_decisions_message(self):
        out = render_pipeline_text(_fake_run(decisions={}))
        assert "no tickers" in out.lower()

    def test_truncates_reasoning(self):
        run = _fake_run(decisions={"X": {"action": "buy", "quantity": 1,
                                         "reasoning": "y" * 500}})
        out = render_pipeline_text(run)
        assert "y" * 500 not in out
