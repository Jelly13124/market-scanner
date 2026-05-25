"""Phase 6B: precompute all indicators used by the 18 v1 blocks.

One pass over each ticker's bars produces a DataFrame with all
needed indicator columns. Signal evaluation (signal_eval.py) reads
this DataFrame instead of recomputing per-bar — keeps simulation
fast even for 500-ticker × 5-year backtests.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class IndicatorMatrix:
    """Per-ticker DataFrame keyed by date, with indicator columns appended
    to the original OHLCV bars."""
    indicators: dict[str, pd.DataFrame] = field(default_factory=dict)


def compute_indicators(bars: dict[str, pd.DataFrame]) -> IndicatorMatrix:
    """Compute all v1 indicators for each ticker's bars.

    Adds columns:
      rsi_14, sma_50, sma_200, ema_12, ema_26, atr_14,
      macd_line, macd_signal, macd_hist,
      bb_upper_20_2, bb_lower_20_2, donchian_high_20, donchian_low_20,
      volume_sma_20

    Returns IndicatorMatrix; original DataFrame columns preserved.
    """
    matrix = IndicatorMatrix()
    for ticker, df in bars.items():
        out = df.copy()
        close = out["close"]
        out["rsi_14"] = _rsi(close, 14)
        out["sma_50"] = close.rolling(50).mean()
        out["sma_200"] = close.rolling(200).mean()
        out["ema_12"] = close.ewm(span=12, adjust=False).mean()
        out["ema_26"] = close.ewm(span=26, adjust=False).mean()
        out["atr_14"] = _atr(out, 14)
        out["macd_line"] = out["ema_12"] - out["ema_26"]
        out["macd_signal"] = out["macd_line"].ewm(span=9, adjust=False).mean()
        out["macd_hist"] = out["macd_line"] - out["macd_signal"]
        bb_mean = close.rolling(20).mean()
        bb_std = close.rolling(20).std()
        out["bb_upper_20_2"] = bb_mean + 2 * bb_std
        out["bb_lower_20_2"] = bb_mean - 2 * bb_std
        out["donchian_high_20"] = out["high"].rolling(20).max()
        out["donchian_low_20"] = out["low"].rolling(20).min()
        out["volume_sma_20"] = out["volume"].rolling(20).mean()
        matrix.indicators[ticker] = out
    return matrix


def _rsi(series: pd.Series, period: int) -> pd.Series:
    """Wilder's RSI on a price series."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    """Average True Range."""
    high = df["high"]; low = df["low"]; close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()
