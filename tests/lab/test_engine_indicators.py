"""Phase 6B: indicator precompute on per-ticker DataFrames."""

from __future__ import annotations

import pandas as pd

from src.lab.engine.indicators import compute_indicators, IndicatorMatrix


def _sample_df(n=300):
    closes = [100 + i * 0.1 for i in range(n)]
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "open": closes, "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes], "close": closes,
            "volume": [1_000_000] * n,
        },
        index=dates,
    )


def test_compute_indicators_adds_columns():
    bars = {"NVDA": _sample_df()}
    matrix = compute_indicators(bars)
    assert isinstance(matrix, IndicatorMatrix)
    nvda = matrix.indicators["NVDA"]
    for col in (
        "rsi_14", "sma_50", "sma_200", "ema_12", "ema_26", "atr_14",
        "macd_line", "macd_signal", "macd_hist",
        "bb_upper_20_2", "bb_lower_20_2",
        "donchian_high_20", "donchian_low_20",
        "volume_sma_20",
    ):
        assert col in nvda.columns, f"missing indicator {col}"
    # RSI in valid range
    rsi_valid = nvda["rsi_14"].dropna()
    assert (rsi_valid >= 0).all() and (rsi_valid <= 100).all()


def test_compute_indicators_handles_short_data():
    """For < 200 bars, sma_200 column exists but is mostly NaN — no crash."""
    bars = {"NVDA": _sample_df(n=50)}
    matrix = compute_indicators(bars)
    assert "sma_200" in matrix.indicators["NVDA"].columns
    assert matrix.indicators["NVDA"]["sma_200"].notna().sum() == 0


def test_compute_indicators_multi_ticker():
    bars = {"NVDA": _sample_df(), "AAPL": _sample_df()}
    matrix = compute_indicators(bars)
    assert set(matrix.indicators.keys()) == {"NVDA", "AAPL"}
