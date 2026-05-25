"""Phase 6C: compute backtest performance metrics."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from src.lab.engine.simulation import Trade


@dataclass
class Metrics:
    total_return: float
    cagr: float
    sharpe: float
    sortino: float
    max_drawdown: float
    calmar: float
    win_rate: float
    profit_factor: float
    avg_holding_days: float
    n_trades: int
    exposure_pct: float  # fraction of bars where any position held


def compute_metrics(
    equity_curve: list[float],
    trades: list[Trade],
    starting_capital: float,
) -> Metrics:
    if not equity_curve:
        return _zero_metrics()
    eq = np.array(equity_curve, dtype=float)
    n_bars = len(eq)
    final = float(eq[-1])
    total_return = (final - starting_capital) / starting_capital if starting_capital else 0.0
    years = n_bars / 252.0 if n_bars > 0 else 1.0
    if final > 0 and starting_capital > 0 and years > 0:
        cagr = (final / starting_capital) ** (1.0 / years) - 1.0
    else:
        cagr = 0.0
    # Daily returns
    rets = np.diff(eq) / eq[:-1] if len(eq) > 1 else np.array([0.0])
    if len(rets) > 1 and rets.std(ddof=1) > 0:
        sharpe = rets.mean() / rets.std(ddof=1) * math.sqrt(252)
    else:
        sharpe = 0.0
    # Sortino: downside std
    downside = rets[rets < 0]
    if len(downside) > 1 and downside.std(ddof=1) > 0:
        sortino = rets.mean() / downside.std(ddof=1) * math.sqrt(252)
    else:
        sortino = 0.0
    # Max drawdown
    peaks = np.maximum.accumulate(eq)
    drawdowns = (eq - peaks) / peaks
    max_dd = float(drawdowns.min()) if len(drawdowns) > 0 else 0.0
    calmar = (cagr / abs(max_dd)) if max_dd < 0 else 0.0
    # Trade-derived metrics
    n_trades = len(trades)
    if n_trades > 0:
        wins = [t.pnl for t in trades if t.pnl > 0]
        losses = [t.pnl for t in trades if t.pnl <= 0]
        win_rate = len(wins) / n_trades
        sum_wins = sum(wins)
        sum_losses = abs(sum(losses))
        profit_factor = sum_wins / sum_losses if sum_losses > 0 else 0.0
        holding = [(t.exit_date - t.entry_date).days for t in trades]
        avg_holding = sum(holding) / len(holding)
    else:
        win_rate = 0.0
        profit_factor = 0.0
        avg_holding = 0.0
    # Exposure — approximate via fraction of bars with non-monotone equity
    # changes (rough). v1 leaves it as 1.0 if we ever had trades, else 0.
    exposure_pct = 1.0 if n_trades > 0 else 0.0
    return Metrics(
        total_return=float(total_return), cagr=float(cagr),
        sharpe=float(sharpe), sortino=float(sortino),
        max_drawdown=float(max_dd), calmar=float(calmar),
        win_rate=float(win_rate), profit_factor=float(profit_factor),
        avg_holding_days=float(avg_holding), n_trades=int(n_trades),
        exposure_pct=float(exposure_pct),
    )


def _zero_metrics() -> Metrics:
    return Metrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
