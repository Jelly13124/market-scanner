"""Phase 6E: end-to-end backtest runner.

run_backtest(spec, db) ->
  1. Resolve universe via Phase 5B watchlist or static index
  2. Load 5y OHLCV via DataLoader
  3. Precompute indicators
  4. Split IS/OOS by time
  5. Simulate IS then OOS
  6. Compute metrics for each
  7. Compute benchmark CAGR (if not 'none')
  8. Build verdict via degradation rules
  9. Return BacktestRunResult (caller persists via BacktestRepository)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import pandas as pd

from src.lab.engine.data import DataLoader
from src.lab.engine.indicators import IndicatorMatrix, compute_indicators
from src.lab.engine.metrics import Metrics, compute_metrics
from src.lab.engine.simulation import run_simulation
from src.lab.engine.universe import UniverseError, load_universe_tickers
from src.lab.engine.verdict import Verdict, make_verdict
from src.lab.spec.strategy import StrategySpec

logger = logging.getLogger(__name__)


@dataclass
class BacktestRunResult:
    spec_snapshot: dict
    start_date: str
    end_date: str
    midpoint_date: str
    universe_size: int
    is_metrics: Metrics | None
    oos_metrics: Metrics | None
    benchmark_cagr: float | None
    verdict: Verdict | None
    is_trades: list = field(default_factory=list)
    oos_trades: list = field(default_factory=list)
    equity_curve_is: list[float] = field(default_factory=list)
    equity_curve_oos: list[float] = field(default_factory=list)
    benchmark_curve: list[float] | None = None
    duration_seconds: float = 0.0
    error_message: str | None = None


def run_backtest(spec: StrategySpec, db: Any) -> BacktestRunResult:
    """End-to-end runner. Returns BacktestRunResult; caller persists it."""
    t0 = time.monotonic()
    cfg = spec.backtest_config

    # Date window defaults: last 5 years if unspecified
    end = date.fromisoformat(cfg.end_date) if cfg.end_date else date.today()
    start = date.fromisoformat(cfg.start_date) if cfg.start_date else (
        end - timedelta(days=5 * 365)
    )
    midpoint = start + timedelta(days=int((end - start).days * cfg.is_oos_split))

    result = BacktestRunResult(
        spec_snapshot=spec.model_dump(),
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        midpoint_date=midpoint.isoformat(),
        universe_size=0,
        is_metrics=None, oos_metrics=None,
        benchmark_cagr=None, verdict=None,
    )

    # 1. Universe
    try:
        tickers = load_universe_tickers(spec.universe, db)
    except UniverseError as e:
        result.error_message = f"Universe error: {e}"
        result.duration_seconds = time.monotonic() - t0
        return result
    result.universe_size = len(tickers)

    # 2. Data load
    loader = DataLoader()
    load_result = loader.load(tickers, start, end)
    if not load_result.bars:
        result.error_message = (
            f"No data loaded for any ticker (universe size {len(tickers)}); "
            f"failed: {len(load_result.failed)}"
        )
        result.duration_seconds = time.monotonic() - t0
        return result

    # 3. Indicators
    matrix = compute_indicators(load_result.bars)

    # 4. Split — slice each ticker's frame by midpoint
    is_matrix = _slice_matrix(matrix, start, midpoint)
    oos_matrix = _slice_matrix(matrix, midpoint, end)

    # 5. Simulate both halves
    is_sim = run_simulation(spec, is_matrix)
    oos_sim = run_simulation(spec, oos_matrix)

    # 6. Metrics
    is_m = compute_metrics(
        is_sim.equity_curve, is_sim.trades,
        starting_capital=cfg.starting_capital_usd,
    )
    oos_m = compute_metrics(
        oos_sim.equity_curve, oos_sim.trades,
        starting_capital=is_sim.equity_curve[-1] if is_sim.equity_curve else cfg.starting_capital_usd,
    )

    # 7. Benchmark CAGR (rough — fetch SPY closes and compute on the same window)
    benchmark_cagr = None
    if cfg.benchmark == "spy":
        benchmark_cagr = _compute_benchmark_cagr(start, end)

    # 8. Verdict
    verdict = make_verdict(is_m, oos_m, benchmark_cagr=benchmark_cagr)

    result.is_metrics = is_m
    result.oos_metrics = oos_m
    result.benchmark_cagr = benchmark_cagr
    result.verdict = verdict
    result.is_trades = [_trade_to_dict(t) for t in is_sim.trades]
    result.oos_trades = [_trade_to_dict(t) for t in oos_sim.trades]
    result.equity_curve_is = is_sim.equity_curve
    result.equity_curve_oos = oos_sim.equity_curve
    result.duration_seconds = time.monotonic() - t0
    return result


def _slice_matrix(matrix: IndicatorMatrix, start: date, end: date) -> IndicatorMatrix:
    sliced: dict[str, pd.DataFrame] = {}
    for ticker, df in matrix.indicators.items():
        mask = (df.index >= pd.Timestamp(start)) & (df.index < pd.Timestamp(end))
        sub = df.loc[mask]
        if not sub.empty:
            sliced[ticker] = sub
    return IndicatorMatrix(indicators=sliced)


def _trade_to_dict(trade) -> dict:
    return {
        "ticker": trade.ticker,
        "entry_date": trade.entry_date.isoformat() if hasattr(trade.entry_date, "isoformat") else str(trade.entry_date),
        "exit_date": trade.exit_date.isoformat() if hasattr(trade.exit_date, "isoformat") else str(trade.exit_date),
        "entry_price": trade.entry_price,
        "exit_price": trade.exit_price,
        "shares": trade.shares,
        "pnl": trade.pnl,
        "exit_reason": trade.exit_reason,
    }


def _compute_benchmark_cagr(start: date, end: date) -> float | None:
    """Simple SPY CAGR via the existing data layer. Returns None on failure."""
    try:
        from src.tools.api import get_prices
        raw = get_prices("SPY", start_date=start.isoformat(), end_date=end.isoformat())
        if not raw:
            return None
        closes = []
        for b in raw:
            if hasattr(b, "close"):
                closes.append(float(b.close))
            elif isinstance(b, dict) and "close" in b:
                closes.append(float(b["close"]))
        if len(closes) < 2:
            return None
        years = (end - start).days / 365.0
        if years <= 0:
            return None
        return (closes[-1] / closes[0]) ** (1.0 / years) - 1.0
    except Exception as e:
        logger.warning("benchmark cagr failed: %s", e)
        return None
