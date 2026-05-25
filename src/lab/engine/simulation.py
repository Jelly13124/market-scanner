"""Phase 6B: per-bar simulation loop.

Iterates dates in order; for each ticker on each date, checks exits
first (close at next-day open), then entries (open at next-day open).
Updates equity curve mark-to-market on the current bar's close.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from src.lab.engine.indicators import IndicatorMatrix
from src.lab.engine.signal_eval import eval_entry, eval_exit, eval_filter
from src.lab.engine.sizing import compute_position_dollars
from src.lab.spec.strategy import StrategySpec


@dataclass
class Position:
    ticker: str
    entry_date: datetime
    entry_price: float
    shares: int
    highest_close: float  # for trailing_stop


@dataclass
class Trade:
    ticker: str
    entry_date: datetime
    exit_date: datetime
    entry_price: float
    exit_price: float
    shares: int
    pnl: float
    exit_reason: str


@dataclass
class SimulationOutput:
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    dates: list[datetime] = field(default_factory=list)
    final_cash: float = 0.0
    final_positions: dict[str, Position] = field(default_factory=dict)


def run_simulation(spec: StrategySpec, matrix: IndicatorMatrix) -> SimulationOutput:
    """Single-pass per-bar simulation."""
    cfg = spec.backtest_config
    cash = float(cfg.starting_capital_usd)
    positions: dict[str, Position] = {}
    trades: list[Trade] = []
    equity_curve: list[float] = []
    out_dates: list[datetime] = []

    if not matrix.indicators:
        return SimulationOutput(
            trades=[], equity_curve=[cash], dates=[],
            final_cash=cash, final_positions={},
        )

    # Build unified date index from union of all tickers
    all_dates = sorted(set().union(*[
        df.index for df in matrix.indicators.values()
    ]))

    cost_pct = (cfg.commission_bps + cfg.slippage_bps) / 10000.0

    for date in all_dates:
        # 1. EXITS
        for ticker, pos in list(positions.items()):
            df = matrix.indicators.get(ticker)
            if df is None or date not in df.index:
                continue
            current_close = float(df.loc[date, "close"])
            current_atr = float(df.loc[date, "atr_14"]) if "atr_14" in df.columns else 0.0
            bars_held = df.index.get_loc(date) - df.index.get_loc(pos.entry_date)
            # Update highest close for trailing stop
            if current_close > pos.highest_close:
                pos.highest_close = current_close
            exit_reason = None
            for exit_block in spec.exit:
                try:
                    if eval_exit(exit_block, ticker, matrix,
                                  position=pos, current_close=current_close,
                                  current_atr=current_atr, bars_held=bars_held):
                        exit_reason = exit_block.type
                        break
                except Exception:
                    continue
            # Reverse-signal-as-exit
            if exit_reason is None and cfg.reverse_signal_as_exit:
                if not _entry_fires(spec, ticker, date, matrix):
                    exit_reason = "reverse_signal"
            if exit_reason:
                cost = current_close * pos.shares * cost_pct
                proceeds = current_close * pos.shares - cost
                cash += proceeds
                pnl = (current_close - pos.entry_price) * pos.shares - cost
                trades.append(Trade(
                    ticker=ticker, entry_date=pos.entry_date, exit_date=date,
                    entry_price=pos.entry_price, exit_price=current_close,
                    shares=pos.shares, pnl=pnl, exit_reason=exit_reason,
                ))
                del positions[ticker]

        # 2. ENTRIES
        if len(positions) < cfg.max_concurrent_positions:
            for ticker, df in matrix.indicators.items():
                if ticker in positions:
                    continue
                if date not in df.index:
                    continue
                if not _filters_pass(spec, ticker, date, matrix):
                    continue
                if not _entry_fires(spec, ticker, date, matrix):
                    continue
                # Compute sizing
                cur_atr = float(df.loc[date, "atr_14"]) if "atr_14" in df.columns else 1.0
                total_equity = cash + sum(
                    p.shares * matrix.indicators[t].loc[date, "close"]
                    if (date in matrix.indicators[t].index) else 0
                    for t, p in positions.items()
                )
                dollars = compute_position_dollars(
                    spec.sizing,
                    cash=cash, total_equity=total_equity,
                    current_positions=len(positions),
                    current_atr=cur_atr if cur_atr > 0 else 1.0,
                )
                if dollars <= 0:
                    continue
                price = float(df.loc[date, "close"])
                shares = int(dollars // price)
                if shares <= 0:
                    continue
                cost = price * shares * cost_pct
                if cash < price * shares + cost:
                    continue
                cash -= price * shares + cost
                positions[ticker] = Position(
                    ticker=ticker, entry_date=date, entry_price=price,
                    shares=shares, highest_close=price,
                )
                if len(positions) >= cfg.max_concurrent_positions:
                    break

        # 3. Mark-to-market
        portfolio = cash
        for t, pos in positions.items():
            df = matrix.indicators.get(t)
            if df is not None and date in df.index:
                portfolio += pos.shares * float(df.loc[date, "close"])
            else:
                portfolio += pos.shares * pos.entry_price
        equity_curve.append(portfolio)
        out_dates.append(date)

    return SimulationOutput(
        trades=trades, equity_curve=equity_curve, dates=out_dates,
        final_cash=cash, final_positions=positions,
    )


def _entry_fires(spec, ticker, date, matrix) -> bool:
    """Evaluate entry group with combiner on a specific date."""
    results = []
    for sig in spec.entry.signals:
        try:
            series = eval_entry(sig, ticker, matrix)
            if date in series.index:
                results.append(bool(series.loc[date]))
            else:
                results.append(False)
        except Exception:
            results.append(False)
    if not results:
        return False
    if spec.entry.combiner == "and":
        return all(results)
    return any(results)


def _filters_pass(spec, ticker, date, matrix) -> bool:
    for f in spec.filters:
        try:
            if not eval_filter(f, ticker, date, matrix):
                return False
        except Exception:
            return False
    return True
