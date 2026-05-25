"""Phase 6B: signal_eval evaluates any block on indicator DataFrame."""

from __future__ import annotations

import pandas as pd

from src.lab.engine.indicators import compute_indicators
from src.lab.engine.signal_eval import (
    eval_entry, eval_exit, eval_filter,
)
from src.lab.spec.blocks_entry import (
    MACrossEntry, RSIEntry, DonchianBreakEntry, VolumeSpikeEntry,
)
from src.lab.spec.blocks_exit import StopLossExit, TimeStopExit
from src.lab.spec.blocks_filters import TrendFilter, LiquidityFilter


def _df_uptrend(n=300, start=100, step=0.5):
    closes = [start + i * step for i in range(n)]
    return pd.DataFrame(
        {
            "open": closes, "high": [c + 0.3 for c in closes],
            "low": [c - 0.3 for c in closes], "close": closes,
            "volume": [1_000_000] * n,
        },
        index=pd.date_range("2020-01-01", periods=n, freq="B"),
    )


def _df_with_spike(n=300):
    df = _df_uptrend(n)
    df.loc[df.index[-5], "volume"] = 10_000_000  # spike on day -5
    return df


def test_ma_cross_golden_fires_in_uptrend():
    bars = {"NVDA": _df_uptrend(300)}
    matrix = compute_indicators(bars)
    block = MACrossEntry(fast=50, slow=200, direction="golden")
    # In a steady uptrend, fast SMA stays above slow → fires after lookback
    series = eval_entry(block, "NVDA", matrix)
    # Should fire on at least the bar where fast first crosses above slow
    assert series.sum() >= 1


def test_rsi_oversold_in_uptrend_does_not_fire():
    bars = {"NVDA": _df_uptrend(300)}
    matrix = compute_indicators(bars)
    block = RSIEntry(period=14, level=30, direction="oversold_buy")
    series = eval_entry(block, "NVDA", matrix)
    # Steady uptrend → RSI stays > 30 → never oversold
    assert series.sum() == 0


def test_donchian_break_up_fires_on_new_high():
    bars = {"NVDA": _df_uptrend(300)}
    matrix = compute_indicators(bars)
    block = DonchianBreakEntry(period=20, direction="break_up")
    series = eval_entry(block, "NVDA", matrix)
    # Monotonic uptrend → every bar above prior 20-day high → fires often
    assert series.sum() > 100


def test_volume_spike_fires_on_spike_day():
    bars = {"NVDA": _df_with_spike(300)}
    matrix = compute_indicators(bars)
    block = VolumeSpikeEntry(avg_period=20, multiplier=3.0)
    series = eval_entry(block, "NVDA", matrix)
    # At least 1 bar should fire (the spike day)
    assert series.sum() >= 1


def test_stop_loss_pct_triggers_when_loss_exceeds():
    # Position entered at 100; current close at 94 = -6% loss; stop 5%
    block = StopLossExit(mode="pct", value=0.05)
    bars = {"NVDA": _df_uptrend(300)}
    matrix = compute_indicators(bars)
    # Build a fake Position object
    from src.lab.engine.simulation import Position
    pos = Position(ticker="NVDA", entry_date=matrix.indicators["NVDA"].index[10],
                   entry_price=100.0, shares=10, highest_close=100.0)
    # Current bar where close < 95 (5% stop)
    # Synthetic test: just pass current price
    triggered = eval_exit(block, "NVDA", matrix, position=pos,
                           current_close=94.0, current_atr=2.0,
                           bars_held=5)
    assert triggered is True
    triggered2 = eval_exit(block, "NVDA", matrix, position=pos,
                            current_close=96.0, current_atr=2.0, bars_held=5)
    assert triggered2 is False


def test_time_stop_triggers_after_n_bars():
    block = TimeStopExit(bars=10)
    bars = {"NVDA": _df_uptrend(300)}
    matrix = compute_indicators(bars)
    from src.lab.engine.simulation import Position
    pos = Position(ticker="NVDA", entry_date=matrix.indicators["NVDA"].index[0],
                   entry_price=100, shares=10, highest_close=100)
    assert eval_exit(block, "NVDA", matrix, position=pos,
                      current_close=105, current_atr=2, bars_held=10) is True
    assert eval_exit(block, "NVDA", matrix, position=pos,
                      current_close=105, current_atr=2, bars_held=9) is False


def test_trend_filter_passes_when_rising():
    bars = {"NVDA": _df_uptrend(300)}
    matrix = compute_indicators(bars)
    block = TrendFilter(ma_period=200, direction="rising")
    # On a bar deep into the uptrend, MA200 slope is positive
    passes = eval_filter(block, "NVDA", matrix.indicators["NVDA"].index[-1], matrix)
    assert passes is True


def test_liquidity_filter_rejects_thin_volume():
    df = _df_uptrend(300)
    df["volume"] = 500  # ~$50k/day — way below $1M default
    bars = {"THIN": df}
    matrix = compute_indicators(bars)
    block = LiquidityFilter(min_daily_dollar_volume=1_000_000, lookback_days=20)
    passes = eval_filter(block, "THIN", matrix.indicators["THIN"].index[-1], matrix)
    assert passes is False
