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


def _section(structured, name="executive_summary", skipped=False):
    return SimpleNamespace(
        name=name,
        markdown="x",
        structured=structured,
        skipped=skipped,
        persona_used=None,
        skip_reason=None,
    )


def _conviction_section(total_score=53):
    return _section(
        {
            "categories": [],
            "weights": [15, 25, 20, 15, 15, 10],
            "total_score": total_score,
            "risk_profile": "balanced",
        },
        name="conviction",
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


def _report_dict(exec_structured, conviction=None):
    sections = {"executive_summary": _section(exec_structured)}
    if conviction is not None:
        sections["conviction"] = conviction
    return {
        "sections": sections,
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


def test_verdict_stock_score_from_conviction():
    """A report with a conviction section scoring 53 → verdict.stock_score == 53,
    and confidence_score is still populated alongside it."""
    d = _report_to_detail(
        _row(),
        report_dict=_report_dict(
            {"recommendation": "buy", "confidence_score": 71, "overall_view": "x"},
            conviction=_conviction_section(total_score=53),
        ),
    )
    assert d.verdict is not None
    assert d.verdict.stock_score == 53
    assert d.verdict.confidence_score == 71


def test_verdict_stock_score_none_when_no_conviction():
    """No conviction section → stock_score is None, confidence still populated."""
    d = _report_to_detail(
        _row(),
        report_dict=_report_dict(
            {"recommendation": "buy", "confidence_score": 71, "overall_view": "x"},
        ),
    )
    assert d.verdict is not None
    assert d.verdict.stock_score is None
    assert d.verdict.confidence_score == 71


def test_verdict_stock_score_recomputed_when_total_missing():
    """If a stored conviction section lacks total_score but kept per-category
    scores, stock_score is recomputed from the same weights (no fork)."""
    conv = _section(
        {
            "categories": [
                {"name": "macro_sector_environment", "score": 60},
                {"name": "company_fundamentals", "score": 60},
                {"name": "valuation_margin_of_safety", "score": 60},
                {"name": "technical_setup", "score": 60},
                {"name": "risk_event_profile", "score": 60},
                {"name": "catalyst_news_quality", "score": 60},
            ],
            "weights": [15, 25, 20, 15, 15, 10],
            "risk_profile": "balanced",
        },
        name="conviction",
    )
    d = _report_to_detail(
        _row(),
        report_dict=_report_dict(
            {"recommendation": "buy", "confidence_score": 71, "overall_view": "x"},
            conviction=conv,
        ),
    )
    # All categories 60 → weighted total is 60 regardless of weights (sum=100).
    assert d.verdict is not None
    assert d.verdict.stock_score == 60
