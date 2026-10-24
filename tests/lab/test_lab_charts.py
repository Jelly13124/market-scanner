"""Phase 6G: chart renderers + chart endpoint."""

from __future__ import annotations

from src.lab.charts import (
    render_equity_curve_png, render_drawdown_png, render_monthly_heatmap_png,
)


def test_equity_curve_png_returns_bytes():
    is_eq = [100000 + i * 100 for i in range(176)]   # 70% of 252
    oos_eq = [is_eq[-1] + i * 50 for i in range(76)]  # remaining 30%
    bench = [100000 + i * 80 for i in range(252)]
    png = render_equity_curve_png(
        is_eq, oos_eq, benchmark_curve=bench, midpoint_label="2023-09-08",
    )
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(png) > 500


def test_equity_curve_empty_returns_no_data_png():
    png = render_equity_curve_png([], [], benchmark_curve=None, midpoint_label="")
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_drawdown_png_returns_bytes():
    eq = [100000, 105000, 110000, 90000, 95000, 120000]
    png = render_drawdown_png(eq)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_drawdown_empty_returns_no_data_png():
    png = render_drawdown_png([])
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_monthly_heatmap_handles_empty():
    """Empty trades -> returns a 'no data' PNG, not a crash."""
    png = render_monthly_heatmap_png(trades=[])
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_monthly_heatmap_handles_undated_trades():
    """Trades without parseable exit_date fall through to 'no dated trades'."""
    png = render_monthly_heatmap_png(trades=[{"pnl": 100.0, "exit_date": ""}])
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_monthly_heatmap_renders_real_trades():
    trades = [
        {"pnl": 1500.0, "exit_date": "2024-01-15"},
        {"pnl": -800.0, "exit_date": "2024-02-20"},
        {"pnl": 2300.0, "exit_date": "2024-06-05"},
        {"pnl": -120.0, "exit_date": "2025-03-11"},
    ]
    png = render_monthly_heatmap_png(trades=trades)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(png) > 500
