"""Tests for v2/pipeline/orchestrator.py.

All tests mock ``run_scan`` and ``run_hedge_fund`` via the injection seams
so nothing hits the network or invokes an LLM. The orchestrator's job is
plumbing — wire the boxes correctly, validate inputs early, build the
scanner_context from ScoredEntry shape.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from v2.pipeline.orchestrator import (
    PipelineResult,
    _entry_to_scanner_context,
    run_pipeline,
)
from v2.scanner.models import ScoredEntry


# ---------------------------------------------------------------------------
# _entry_to_scanner_context — pure transform
# ---------------------------------------------------------------------------


def _trigger(detector: str, *, fired: bool = True, components: dict | None = None):
    """Build a trigger dict (matches EventTrigger.model_dump shape)."""
    return {
        "detector": detector,
        "triggered": fired,
        "severity_z": 2.5 if fired else 0.0,
        "direction": "bullish",
        "reason": "",
        "components": components or {},
        "asof_date": "2024-08-01",
    }


class TestEntryToScannerContext:
    def test_keeps_only_triggered_detectors(self):
        entry = ScoredEntry(
            ticker="AAPL", composite_score=87.5, direction="bullish",
            event_score=87.5, event_severity=2.5, rank=1,
            triggers=[
                _trigger("earnings_event", fired=True,
                         components={"phase": 2.0, "raw_z": 2.5}),
                _trigger("bollinger_squeeze", fired=False),  # should be dropped
                _trigger("obv_divergence", fired=True,
                         components={"obv_slope_z": 1.5}),
            ],
        )
        ctx = _entry_to_scanner_context(entry, "2024-08-01")
        assert ctx["scan_date"] == "2024-08-01"
        assert ctx["rank"] == 1
        assert ctx["composite_score"] == 87.5
        assert ctx["direction"] == "bullish"
        assert sorted(ctx["triggered_detectors"]) == ["earnings_event", "obv_divergence"]
        # Components carry through verbatim, only for fired detectors
        assert ctx["triggered_components"]["earnings_event"]["phase"] == 2.0
        assert "bollinger_squeeze" not in ctx["triggered_components"]

    def test_no_triggers_produces_empty_lists(self):
        entry = ScoredEntry(
            ticker="AAPL", composite_score=50.0, direction="neutral",
            event_score=50.0, rank=1, triggers=[],
        )
        ctx = _entry_to_scanner_context(entry, "2024-08-01")
        assert ctx["triggered_detectors"] == []
        assert ctx["triggered_components"] == {}


# ---------------------------------------------------------------------------
# run_pipeline — composition / validation
# ---------------------------------------------------------------------------


def _scored(ticker: str, rank: int = 1, **overrides) -> ScoredEntry:
    base = dict(
        ticker=ticker, composite_score=80.0, direction="bullish",
        event_score=80.0, event_severity=2.0, rank=rank,
        triggers=[_trigger("earnings_event", components={"raw_z": 2.5})],
    )
    base.update(overrides)
    return ScoredEntry(**base)


def _fake_hedge_fund(captured: dict):
    """Return a fake run_hedge_fund that captures kwargs + returns a
    canned result."""
    def _impl(*, tickers, start_date, end_date, portfolio, show_reasoning,
              selected_analysts, model_name, model_provider, scanner_context,
              macro_context=None):
        captured["tickers"] = tickers
        captured["start_date"] = start_date
        captured["end_date"] = end_date
        captured["selected_analysts"] = list(selected_analysts)
        captured["scanner_context"] = scanner_context
        captured["macro_context"] = macro_context
        captured["model_name"] = model_name
        return {
            "decisions": {t: {"action": "hold", "quantity": 0} for t in tickers},
            "analyst_signals": {
                "scanner_signal_agent": {
                    t: {"signal": "bullish", "confidence": 80, "reasoning": "x"}
                    for t in tickers
                },
            },
        }
    return _impl


class TestRunPipelineComposition:
    def test_fails_fast_on_unknown_template(self):
        with pytest.raises(ValueError, match="unknown template"):
            run_pipeline(template="no_such")

    def test_fails_fast_on_both_template_and_custom(self):
        with pytest.raises(ValueError, match="either template OR custom"):
            run_pipeline(template="balanced", custom_analysts=["warren_buffett"])

    def test_basic_run_routes_scanner_context_to_workflow(self):
        captured = {}
        scored = [_scored("AAPL", rank=1), _scored("NVDA", rank=2)]

        result = run_pipeline(
            scan_date="2024-08-01",
            universe="custom", universe_tickers=["AAPL", "NVDA", "MSFT"],
            top_n=2, template="quick",
            run_scan_fn=lambda **kw: scored,
            run_hedge_fund_fn=_fake_hedge_fund(captured),
            persist=False,
        )

        # The fake captured the kwargs we passed through.
        assert captured["tickers"] == ["AAPL", "NVDA"]
        assert captured["end_date"] == "2024-08-01"
        # scanner_context keyed by ticker
        assert set(captured["scanner_context"]) == {"AAPL", "NVDA"}
        # And each entry has the translated shape
        ctx_aapl = captured["scanner_context"]["AAPL"]
        assert ctx_aapl["rank"] == 1
        assert ctx_aapl["direction"] == "bullish"
        assert "earnings_event" in ctx_aapl["triggered_detectors"]
        # template "quick" → 5 analysts (scanner_signal + 4 analyst nodes)
        assert "scanner_signal" in captured["selected_analysts"]
        assert len(captured["selected_analysts"]) == 5

        # And the result is well-formed.
        assert isinstance(result, PipelineResult)
        assert result.status == "complete"
        assert result.template == "quick"
        assert len(result.watchlist) == 2
        assert result.agent_decisions == {"AAPL": {"action": "hold", "quantity": 0},
                                          "NVDA": {"action": "hold", "quantity": 0}}
        assert result.run_id  # UUID populated
        assert result.duration_seconds >= 0

    def test_empty_scan_returns_clean_result_without_invoking_workflow(self):
        captured = {}
        result = run_pipeline(
            scan_date="2024-08-01",
            universe="custom", universe_tickers=["AAPL"],
            top_n=5, template="quick",
            run_scan_fn=lambda **kw: [],            # scanner produced nothing
            run_hedge_fund_fn=_fake_hedge_fund(captured),
            persist=False,
        )
        # workflow was NOT called
        assert "tickers" not in captured
        assert result.status == "complete"
        assert result.watchlist == []
        assert result.agent_decisions == {}

    def test_custom_analysts_passes_through(self):
        captured = {}
        run_pipeline(
            scan_date="2024-08-01",
            universe="custom", universe_tickers=["AAPL"],
            top_n=1,
            custom_analysts=["warren_buffett", "michael_burry"],
            run_scan_fn=lambda **kw: [_scored("AAPL")],
            run_hedge_fund_fn=_fake_hedge_fund(captured),
            persist=False,
        )
        # scanner_signal auto-prepended; user's picks preserved
        assert captured["selected_analysts"][0] == "scanner_signal"
        assert "warren_buffett" in captured["selected_analysts"]
        assert "michael_burry" in captured["selected_analysts"]

    def test_default_template_used_when_neither_arg_given(self):
        captured = {}
        result = run_pipeline(
            scan_date="2024-08-01",
            universe="custom", universe_tickers=["AAPL"],
            top_n=1,
            # template=None, custom_analysts=None
            run_scan_fn=lambda **kw: [_scored("AAPL")],
            run_hedge_fund_fn=_fake_hedge_fund(captured),
            persist=False,
        )
        from v2.pipeline.templates import DEFAULT_TEMPLATE, TEMPLATES
        assert result.template == DEFAULT_TEMPLATE
        assert captured["selected_analysts"] == TEMPLATES[DEFAULT_TEMPLATE]

    def test_start_date_is_scan_date_minus_250_days(self):
        captured = {}
        run_pipeline(
            scan_date="2024-08-01",
            universe="custom", universe_tickers=["AAPL"],
            top_n=1, template="quick",
            run_scan_fn=lambda **kw: [_scored("AAPL")],
            run_hedge_fund_fn=_fake_hedge_fund(captured),
            persist=False,
        )
        # Agents get ~250 calendar days (~180 trading days) of history —
        # required for technical_analyst's 126-trading-day momentum_6m
        # rolling window. 90 days only yields ~63 trading days, leaving
        # momentum_6m / hurst NaN→0 for every ticker.
        assert captured["start_date"] == "2023-11-25"
        assert captured["end_date"] == "2024-08-01"

    def test_persist_true_does_not_crash_v1_no_op(self):
        # Phase 3 wires real persistence; Phase 2 just logs.
        captured = {}
        result = run_pipeline(
            scan_date="2024-08-01",
            universe="custom", universe_tickers=["AAPL"],
            top_n=1, template="quick",
            run_scan_fn=lambda **kw: [_scored("AAPL")],
            run_hedge_fund_fn=_fake_hedge_fund(captured),
            persist=True,
        )
        assert result.status == "complete"
