"""Phase 6B: evaluate any block (entry/exit/filter) on the indicator matrix.

eval_entry / eval_exit / eval_filter dispatch on block.type and read
the precomputed indicator columns. Engine calls these once per bar
per ticker — no recomputation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from src.lab.engine.indicators import IndicatorMatrix
from src.lab.spec.blocks_entry import (
    BollingerBreakEntry, DonchianBreakEntry, MACDEntry, MACrossEntry,
    PriceVsMAEntry, RSICrossEntry, RSIEntry, VolumeSpikeEntry,
)
from src.lab.spec.blocks_exit import (
    StopLossExit, TakeProfitExit, TimeStopExit, TrailingStopExit,
)
from src.lab.spec.blocks_filters import (
    LiquidityFilter, TrendFilter, VolatilityFilter,
)

if TYPE_CHECKING:
    from src.lab.engine.simulation import Position


def eval_entry(block, ticker: str, matrix: IndicatorMatrix) -> pd.Series:
    """Return bool Series aligned with matrix.indicators[ticker].index;
    True where the entry signal fires."""
    df = matrix.indicators[ticker]
    t = block.type

    if t == "rsi":
        col = df[f"rsi_{block.period}"] if f"rsi_{block.period}" in df.columns else _rsi_for(df, block.period)
        if block.direction == "oversold_buy":
            return col < block.level
        return col > block.level  # overbought_short — v1 long-only treats as no-op

    if t == "rsi_cross":
        col = df[f"rsi_{block.period}"] if f"rsi_{block.period}" in df.columns else _rsi_for(df, block.period)
        prev = col.shift(1)
        if block.direction == "up":
            return (prev < block.level) & (col >= block.level)
        return (prev > block.level) & (col <= block.level)

    if t == "ma_cross":
        fast = _ma_for(df, block.fast, block.ma_type)
        slow = _ma_for(df, block.slow, block.ma_type)
        diff = fast - slow
        prev_diff = diff.shift(1)
        # Treat NaN prev as "below zero" so the first bar where slow becomes
        # computable and fast > slow registers as a golden cross (and the
        # symmetric case for death cross).
        if block.direction == "golden":
            return (prev_diff.fillna(-1.0) <= 0) & (diff.fillna(0.0) > 0)
        return (prev_diff.fillna(1.0) >= 0) & (diff.fillna(0.0) < 0)

    if t == "price_vs_ma":
        ma = _ma_for(df, block.ma_period, block.ma_type)
        if block.direction == "above":
            return df["close"] > ma
        return df["close"] < ma

    if t == "macd":
        line = df["macd_line"]; sig = df["macd_signal"]; hist = df["macd_hist"]
        prev_line = line.shift(1); prev_sig = sig.shift(1)
        prev_hist = hist.shift(1)
        if block.trigger == "bullish_cross":
            return (prev_line <= prev_sig) & (line > sig)
        if block.trigger == "bearish_cross":
            return (prev_line >= prev_sig) & (line < sig)
        if block.trigger == "histogram_flip_up":
            return (prev_hist <= 0) & (hist > 0)
        return (prev_hist >= 0) & (hist < 0)  # histogram_flip_down

    if t == "bollinger_break":
        upper = df["bb_upper_20_2"]; lower = df["bb_lower_20_2"]
        if block.direction == "break_up":
            return df["close"] > upper
        return df["close"] < lower

    if t == "donchian_break":
        # Lookback to N bars BEFORE the current bar (exclude today's high/low)
        prev_high = df["high"].shift(1).rolling(block.period).max()
        prev_low = df["low"].shift(1).rolling(block.period).min()
        if block.direction == "break_up":
            return df["close"] > prev_high
        return df["close"] < prev_low

    if t == "volume_spike":
        avg = df["volume"].rolling(block.avg_period).mean()
        return df["volume"] > block.multiplier * avg

    raise ValueError(f"Unknown entry block type: {t}")


def eval_exit(
    block, ticker: str, matrix: IndicatorMatrix, *,
    position: "Position",
    current_close: float, current_atr: float, bars_held: int,
) -> bool:
    """Return True if this exit block triggers on the current bar."""
    t = block.type
    if t == "stop_loss":
        loss = (position.entry_price - current_close) / position.entry_price
        if block.mode == "pct":
            return loss >= block.value
        # atr mode
        stop_distance = block.value * current_atr
        return (position.entry_price - current_close) >= stop_distance

    if t == "take_profit":
        gain = (current_close - position.entry_price) / position.entry_price
        return gain >= block.pct

    if t == "trailing_stop":
        peak = position.highest_close
        if block.mode == "pct":
            return (peak - current_close) / peak >= block.value
        return (peak - current_close) >= block.value * current_atr

    if t == "time_stop":
        return bars_held >= block.bars

    raise ValueError(f"Unknown exit block type: {t}")


def eval_filter(block, ticker: str, date, matrix: IndicatorMatrix) -> bool:
    """Return True if this filter passes (entry allowed) on the given date."""
    df = matrix.indicators[ticker]
    t = block.type
    if t == "trend":
        ma = _ma_for(df, block.ma_period, block.ma_type)
        # Use 5-bar slope
        cur = ma.loc[date]
        prev_idx_pos = df.index.get_loc(date) - 5
        if prev_idx_pos < 0:
            return False
        prev = ma.iloc[prev_idx_pos]
        if pd.isna(cur) or pd.isna(prev):
            return False
        if block.direction == "rising":
            return bool(cur > prev)
        return bool(cur < prev)

    if t == "volatility":
        atr_col = f"atr_{block.atr_period}" if f"atr_{block.atr_period}" in df.columns else None
        if atr_col is None:
            # Compute on the fly if not precomputed
            from src.lab.engine.indicators import _atr
            atr = _atr(df, block.atr_period)
        else:
            atr = df[atr_col]
        cur = atr.loc[date]
        if pd.isna(cur):
            return False
        # Percentile of current ATR vs trailing
        trailing = atr.loc[:date].dropna()
        if len(trailing) < 30:
            return False
        rank_pct = (trailing < cur).mean() * 100
        return bool(block.percentile_min <= rank_pct <= block.percentile_max)

    if t == "liquidity":
        dollar_vol = (df["close"] * df["volume"]).rolling(block.lookback_days).mean()
        cur = dollar_vol.loc[date]
        if pd.isna(cur):
            return False
        return bool(cur >= block.min_daily_dollar_volume)

    raise ValueError(f"Unknown filter block type: {t}")


def _rsi_for(df: pd.DataFrame, period: int) -> pd.Series:
    from src.lab.engine.indicators import _rsi
    return _rsi(df["close"], period)


def _ma_for(df: pd.DataFrame, period: int, ma_type: str) -> pd.Series:
    if ma_type == "sma":
        return df["close"].rolling(period).mean()
    return df["close"].ewm(span=period, adjust=False).mean()
