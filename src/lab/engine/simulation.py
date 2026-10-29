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
    entry_cost: float = 0.0


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
    """Evaluate at the close, fill at the next available bar's open.

    Unfilled signals at the end of the window expire. Open positions remain
    marked to the last available close; they are not implicitly liquidated.
    """
    cfg = spec.backtest_config
    cash = float(cfg.starting_capital_usd)
    positions: dict[str, Position] = {}
    trades: list[Trade] = []
    equity_curve: list[float] = []
    out_dates: list[datetime] = []
    pending_entries: dict[str, float] = {}  # signal-day ATR for sizing
    pending_exits: dict[str, str] = {}
    last_closes: dict[str, float] = {}

    if not matrix.indicators:
        return SimulationOutput(equity_curve=[cash], final_cash=cash)

    all_dates = sorted(set().union(*[df.index for df in matrix.indicators.values()]))
    cost_pct = (cfg.commission_bps + cfg.slippage_bps) / 10000.0

    for date in all_dates:
        # Fill yesterday's exits first, using today's open (including gaps).
        for ticker, reason in list(pending_exits.items()):
            df = matrix.indicators[ticker]
            if date not in df.index:
                continue
            pos = positions.pop(ticker)
            price = float(df.loc[date, "open"])
            cost = price * pos.shares * cost_pct
            cash += price * pos.shares - cost
            trades.append(Trade(
                ticker=ticker, entry_date=pos.entry_date, exit_date=date,
                entry_price=pos.entry_price, exit_price=price, shares=pos.shares,
                pnl=(price - pos.entry_price) * pos.shares - pos.entry_cost - cost,
                exit_reason=reason,
            ))
            del pending_exits[ticker]

        for ticker, signal_atr in list(pending_entries.items()):
            df = matrix.indicators[ticker]
            if date not in df.index:
                continue
            del pending_entries[ticker]
            if len(positions) >= cfg.max_concurrent_positions:
                continue
            price = float(df.loc[date, "open"])
            # No current-day close is known at execution time.
            equity_at_open = cash + sum(
                pos.shares * (float(matrix.indicators[t].loc[date, "open"])
                              if date in matrix.indicators[t].index else last_closes[t])
                for t, pos in positions.items()
            )
            dollars = compute_position_dollars(
                spec.sizing, cash=cash, total_equity=equity_at_open,
                current_positions=len(positions), current_atr=signal_atr,
            )
            shares = int(min(dollars, cash / (1 + cost_pct)) // price)
            if shares <= 0:
                continue
            cost = price * shares * cost_pct
            cash -= price * shares + cost
            positions[ticker] = Position(
                ticker=ticker, entry_date=date, entry_price=price,
                shares=shares, highest_close=price, entry_cost=cost,
            )

        # Signals are evaluated only after this bar closes.
        for ticker, df in matrix.indicators.items():
            if date not in df.index:
                continue
            close = float(df.loc[date, "close"])
            last_closes[ticker] = close
            atr = float(df.loc[date, "atr_14"]) if "atr_14" in df.columns else 0.0
            if ticker in positions:
                pos = positions[ticker]
                pos.highest_close = max(pos.highest_close, close)
                bars_held = df.index.get_loc(date) - df.index.get_loc(pos.entry_date)
                for block in spec.exit:
                    if eval_exit(block, ticker, matrix, position=pos,
                                 current_close=close, current_atr=atr, bars_held=bars_held):
                        pending_exits[ticker] = block.type
                        break
                if ticker not in pending_exits and cfg.reverse_signal_as_exit and not _entry_fires(spec, ticker, date, matrix):
                    pending_exits[ticker] = "reverse_signal"
            elif _filters_pass(spec, ticker, date, matrix) and _entry_fires(spec, ticker, date, matrix):
                pending_entries[ticker] = atr if atr > 0 else 1.0

        equity_curve.append(cash + sum(pos.shares * last_closes[t] for t, pos in positions.items()))
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
