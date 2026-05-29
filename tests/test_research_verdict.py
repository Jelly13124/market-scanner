"""Tests for verdict extraction in _report_to_detail (research.py).

Covers:
- valid recommendation → verdict populated
- invalid recommendation → verdict is None
- missing executive_summary section → verdict is None
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from app.backend.routes.research import _report_to_detail


def _section(structured):
    return SimpleNamespace(
        name="executive_summary",
        markdown="x",
        structured=structured,
        skipped=False,
        persona_used=None,
        skip_reason=None,
    )


def _row():
    return SimpleNamespace(
        id=1,
        ticker="AAPL",
        scan_date="2026-05-28",
        created_at=datetime(2026, 5, 28),
        duration_seconds=1.0,
        analyze_request_json={},
    )


def _report_dict(exec_structured):
    return {
        "sections": {"executive_summary": _section(exec_structured)},
        "backtest": None,
        "persona_assignments": None,
    }


def test_verdict_populated():
    d = _report_to_detail(
        _row(),
        report_dict=_report_dict(
            {"recommendation": "buy", "confidence_score": 71, "overall_view": "strong moat"}
        ),
    )
    assert d.verdict is not None
    assert d.verdict.recommendation == "buy"
    assert d.verdict.confidence_score == 71
    assert d.verdict.one_liner == "strong moat"


def test_verdict_strong_buy():
    d = _report_to_detail(
        _row(),
        report_dict=_report_dict(
            {"recommendation": "strong_buy", "confidence_score": 90, "overall_view": ""}
        ),
    )
    assert d.verdict is not None
    assert d.verdict.recommendation == "strong_buy"


def test_verdict_invalid_recommendation_is_none():
    d = _report_to_detail(
        _row(),
        report_dict=_report_dict(
            {"recommendation": "??", "confidence_score": 50, "overall_view": "x"}
        ),
    )
    assert d.verdict is None


def test_verdict_missing_exec_is_none():
    d = _report_to_detail(
        _row(),
        report_dict={"sections": {}, "backtest": None, "persona_assignments": None},
    )
    assert d.verdict is None


def test_verdict_non_dict_structured_is_none():
    """structured=None (e.g. LLM returned no structured output) → verdict None."""
    d = _report_to_detail(
        _row(),
        report_dict=_report_dict(None),
    )
    assert d.verdict is None
