"""Phase 6C: metrics from equity curve + trades."""

from __future__ import annotations

import math

from src.lab.engine.metrics import compute_metrics, Metrics
from src.lab.engine.simulation import Trade


def _trade(pnl: float, entry_day: int = 0, exit_day: int = 5):
    from datetime import datetime, timedelta
    base = datetime(2020, 1, 1)
    return Trade(
        ticker="X", entry_date=base + timedelta(days=entry_day),
        exit_date=base + timedelta(days=exit_day),
        entry_price=100, exit_price=100 + pnl / 10,
        shares=10, pnl=pnl, exit_reason="stop_loss" if pnl < 0 else "take_profit",
    )


def test_basic_metrics_monotonic_uptrend():
    equity = [100_000 + i * 100 for i in range(252)]  # +25.2% over 252 bars
    trades = [_trade(100), _trade(200), _trade(-50)]
    m = compute_metrics(equity, trades, starting_capital=100_000)
    assert isinstance(m, Metrics)
    assert 0.24 < m.total_return < 0.26
    assert m.cagr > 0.20  # ~25% in 1 year
    assert m.sharpe > 0  # smooth uptrend → positive sharpe
    assert m.n_trades == 3
    assert m.win_rate == 2 / 3
    # profit factor: wins (300) / abs(losses 50) = 6
    assert 5.5 < m.profit_factor < 6.5


def test_zero_trades_returns_zero_metrics():
    equity = [100_000] * 252  # flat
    m = compute_metrics(equity, [], starting_capital=100_000)
    assert m.n_trades == 0
    assert m.win_rate == 0
    assert m.profit_factor == 0
    assert m.total_return == 0.0


def test_max_drawdown_detects_pullback():
    equity = [100_000, 105_000, 110_000, 90_000, 95_000, 120_000]
    m = compute_metrics(equity, [], starting_capital=100_000)
    # peak 110k, trough 90k → -18.2%
    assert -0.19 < m.max_drawdown < -0.17
