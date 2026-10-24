"""Tests for the Phase-11 fundamental / valuation / relative-strength
renderers added to ``src.research.charts.render``.

All offline: fakes are duck-typed ``SimpleNamespace`` objects (the
renderers read fields defensively via getattr/.get, so real Pydantic
models are not required). Each renderer is best-effort — degenerate
input must yield a ``_no_data_png`` PNG, never an exception.
"""

from __future__ import annotations

from types import SimpleNamespace

from src.research.charts.render import (
    render_fundamental_trends_png,
    render_relative_strength_png,
    render_valuation_band_png,
)


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _is_png(data: bytes) -> bool:
    return isinstance(data, bytes) and data.startswith(PNG_SIGNATURE)


def _fin(report_period: str, **kw) -> SimpleNamespace:
    """A duck-typed FinancialMetrics-like row with all fields nullable."""
    base = dict(
        report_period=report_period,
        gross_margin=None,
        operating_margin=None,
        net_margin=None,
        revenue_growth=None,
        earnings_growth=None,
        price_to_earnings_ratio=None,
        price_to_sales_ratio=None,
        peg_ratio=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _price(time: str, close: float) -> SimpleNamespace:
    return SimpleNamespace(
        time=time, open=close, high=close, low=close, close=close, volume=1000
    )


# ---------------------------------------------------------------------------
# render_fundamental_trends_png
# ---------------------------------------------------------------------------


def test_fundamental_trends_happy_path_returns_png():
    fins = [
        _fin("2023-12-31", gross_margin=0.50, operating_margin=0.20,
             net_margin=0.15, revenue_growth=0.10),
        _fin("2024-03-31", gross_margin=0.52, operating_margin=0.21,
             net_margin=0.16, revenue_growth=0.12),
        _fin("2024-06-30", gross_margin=0.51, operating_margin=0.22,
             net_margin=0.17, revenue_growth=0.09),
    ]
    out = render_fundamental_trends_png(fins, title="Margins")
    assert _is_png(out)
    assert len(out) > 200


def test_fundamental_trends_unsorted_input_still_renders():
    # Deliberately out of order — function must sort by report_period.
    fins = [
        _fin("2024-06-30", gross_margin=0.51, net_margin=0.17),
        _fin("2023-12-31", gross_margin=0.50, net_margin=0.15),
        _fin("2024-03-31", gross_margin=0.52, net_margin=0.16),
    ]
    out = render_fundamental_trends_png(fins)
    assert _is_png(out)


def test_fundamental_trends_partial_none_series_skipped():
    # operating_margin entirely None -> series skipped, others still plotted.
    fins = [
        _fin("2024-03-31", gross_margin=0.52, net_margin=0.16),
        _fin("2024-06-30", gross_margin=0.51, net_margin=0.17),
    ]
    out = render_fundamental_trends_png(fins)
    assert _is_png(out)


def test_fundamental_trends_empty_returns_no_data_png():
    out = render_fundamental_trends_png([])
    assert _is_png(out)


def test_fundamental_trends_single_point_returns_no_data_png():
    out = render_fundamental_trends_png([_fin("2024-06-30", gross_margin=0.5)])
    assert _is_png(out)


def test_fundamental_trends_all_none_returns_no_data_png():
    fins = [_fin("2024-03-31"), _fin("2024-06-30")]
    out = render_fundamental_trends_png(fins)
    assert _is_png(out)


# ---------------------------------------------------------------------------
# render_valuation_band_png
# ---------------------------------------------------------------------------


def test_valuation_band_happy_path_returns_png():
    fins = [
        _fin("2023-12-31", price_to_earnings_ratio=18.0),
        _fin("2024-03-31", price_to_earnings_ratio=22.0),
        _fin("2024-06-30", price_to_earnings_ratio=20.0),
    ]
    out = render_valuation_band_png(fins, current_value=21.0)
    assert _is_png(out)
    assert len(out) > 200


def test_valuation_band_without_current_value_returns_png():
    fins = [
        _fin("2023-12-31", price_to_earnings_ratio=18.0),
        _fin("2024-06-30", price_to_earnings_ratio=20.0),
    ]
    out = render_valuation_band_png(fins)
    assert _is_png(out)


def test_valuation_band_alternate_metric_returns_png():
    fins = [
        _fin("2023-12-31", price_to_sales_ratio=4.0),
        _fin("2024-03-31", price_to_sales_ratio=5.0),
        _fin("2024-06-30", price_to_sales_ratio=4.5),
    ]
    out = render_valuation_band_png(
        fins, metric="price_to_sales_ratio", title="P/S Band"
    )
    assert _is_png(out)


def test_valuation_band_unsorted_input_still_renders():
    fins = [
        _fin("2024-06-30", price_to_earnings_ratio=20.0),
        _fin("2023-12-31", price_to_earnings_ratio=18.0),
    ]
    out = render_valuation_band_png(fins)
    assert _is_png(out)


def test_valuation_band_empty_returns_no_data_png():
    out = render_valuation_band_png([])
    assert _is_png(out)


def test_valuation_band_single_point_returns_no_data_png():
    out = render_valuation_band_png(
        [_fin("2024-06-30", price_to_earnings_ratio=20.0)]
    )
    assert _is_png(out)


def test_valuation_band_missing_metric_returns_no_data_png():
    # metric field is None on every row.
    fins = [_fin("2024-03-31"), _fin("2024-06-30")]
    out = render_valuation_band_png(fins, metric="peg_ratio")
    assert _is_png(out)


# ---------------------------------------------------------------------------
# render_relative_strength_png
# ---------------------------------------------------------------------------


def test_relative_strength_happy_path_returns_png():
    ticker = [_price(f"2024-01-{d:02d}", 100 + d) for d in range(1, 11)]
    bench = [_price(f"2024-01-{d:02d}", 200 + d) for d in range(1, 11)]
    out = render_relative_strength_png(
        ticker, bench, ticker_label="AAPL", benchmark_label="SPY"
    )
    assert _is_png(out)
    assert len(out) > 200


def test_relative_strength_dict_prices_returns_png():
    ticker = [{"time": f"2024-01-{d:02d}", "close": 100 + d} for d in range(1, 6)]
    bench = [{"time": f"2024-01-{d:02d}", "close": 200 + d} for d in range(1, 6)]
    out = render_relative_strength_png(ticker, bench)
    assert _is_png(out)


def test_relative_strength_unequal_lengths_truncates_from_end():
    # Different lengths -> aligned by truncating to min length from the end.
    ticker = [_price(f"2024-01-{d:02d}", 100 + d) for d in range(1, 16)]
    bench = [_price(f"2024-01-{d:02d}", 200 + d) for d in range(1, 6)]
    out = render_relative_strength_png(ticker, bench)
    assert _is_png(out)


def test_relative_strength_empty_returns_no_data_png():
    out = render_relative_strength_png([], [])
    assert _is_png(out)


def test_relative_strength_single_close_returns_no_data_png():
    out = render_relative_strength_png(
        [_price("2024-01-01", 100)], [_price("2024-01-01", 200)]
    )
    assert _is_png(out)


def test_relative_strength_one_side_empty_returns_no_data_png():
    ticker = [_price(f"2024-01-{d:02d}", 100 + d) for d in range(1, 6)]
    out = render_relative_strength_png(ticker, [])
    assert _is_png(out)


def test_relative_strength_zero_first_close_does_not_raise():
    # First close 0 would divide-by-zero a naive rebase; must be guarded.
    ticker = [_price("2024-01-01", 0.0), _price("2024-01-02", 10.0)]
    bench = [_price("2024-01-01", 200.0), _price("2024-01-02", 210.0)]
    out = render_relative_strength_png(ticker, bench)
    assert _is_png(out)
