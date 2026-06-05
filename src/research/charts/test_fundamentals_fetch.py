"""Offline tests for fetch_fundamental_history (margins / growth from yfinance
income statements). search_line_items + yfinance are mocked — no network."""

from types import SimpleNamespace
from unittest.mock import patch

from src.research.charts.fundamentals_fetch import fetch_fundamental_history


def _li(rp, rev, gp, oi, ni, eps=None):
    return SimpleNamespace(
        report_period=rp, revenue=rev, gross_profit=gp,
        operating_income=oi, net_income=ni, earnings_per_share=eps,
    )


def _run(items):
    # search_line_items is imported inside the function → patch the source.
    # yfinance.Ticker raises → the P/E block bails (offline), margins still computed.
    with patch("src.tools.line_items.search_line_items", return_value=items), \
            patch("yfinance.Ticker", side_effect=RuntimeError("no network in test")):
        return fetch_fundamental_history("ADBE", "2025-12-01")


def test_computes_margins_and_period_over_period_growth():
    out = _run([
        _li("2025-11-30", 100.0, 89.0, 36.0, 30.0),   # newest-first
        _li("2024-11-30", 90.0, 80.0, 32.0, 25.0),
    ])
    assert len(out) == 2
    o0 = out[0]
    assert abs(o0.gross_margin - 0.89) < 1e-9
    assert abs(o0.operating_margin - 0.36) < 1e-9
    assert abs(o0.net_margin - 0.30) < 1e-9
    assert abs(o0.revenue_growth - (100.0 / 90.0 - 1.0)) < 1e-9
    # oldest period has no prior → growth None
    assert out[1].revenue_growth is None
    # P/E is None when yfinance is unavailable (no crash)
    assert o0.price_to_earnings_ratio is None


def test_none_revenue_yields_none_margins_not_crash():
    out = _run([_li("2025-11-30", None, 89.0, 36.0, 30.0),
                _li("2024-11-30", 90.0, 80.0, 32.0, 25.0)])
    assert out[0].gross_margin is None  # rev is None → no divide
    assert out[0].net_margin is None


def test_empty_items_returns_empty():
    assert _run([]) == []


def test_search_failure_returns_empty():
    with patch("src.tools.line_items.search_line_items", side_effect=RuntimeError("boom")):
        assert fetch_fundamental_history("X", "2025-01-01") == []
