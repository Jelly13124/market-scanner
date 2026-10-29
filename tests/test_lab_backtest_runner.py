"""Phase 6E: end-to-end backtest_runner ties all engine pieces together."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from src.lab.backtest_runner import BacktestRunResult, run_backtest
from src.lab.spec.blocks_entry import DonchianBreakEntry
from src.lab.spec.blocks_exit import StopLossExit, TimeStopExit
from src.lab.spec.blocks_sizing import FixedPctSizing
from src.lab.spec.strategy import (
    BacktestConfig,
    EntryGroup,
    StrategySpec,
    UniverseSpec,
)


def _df_uptrend(n=500):
    closes = [100 + i * 0.2 for i in range(n)]
    return pd.DataFrame(
        {
            "open": closes, "high": [c + 0.3 for c in closes],
            "low": [c - 0.3 for c in closes], "close": closes,
            "volume": [10_000_000] * n,
        },
        index=pd.date_range("2020-01-01", periods=n, freq="B"),
    )


def _minimal_spec():
    return StrategySpec(
        name="E2E",
        description="",
        universe=UniverseSpec(kind="sp500"),
        entry=EntryGroup(combiner="and", signals=[
            DonchianBreakEntry(period=20, direction="break_up"),
        ]),
        exit=[StopLossExit(mode="pct", value=0.05), TimeStopExit(bars=30)],
        filters=[],
        sizing=FixedPctSizing(pct=0.10),
        backtest_config=BacktestConfig(
            starting_capital_usd=100_000,
            max_concurrent_positions=5,
            is_oos_split=0.7,
            benchmark="none",  # skip benchmark fetch in test
        ),
    )


@patch("src.lab.backtest_runner.DataLoader")
@patch("src.lab.backtest_runner.load_universe_tickers")
def test_e2e_run_produces_complete_result(mock_universe, mock_loader_cls):
    # Mock universe
    mock_universe.return_value = ["NVDA", "AAPL", "MSFT"]
    # Mock DataLoader to return synthetic uptrend bars
    from src.lab.engine.data import DataLoadResult
    mock_loader_cls.return_value.load.return_value = DataLoadResult(
        bars={"NVDA": _df_uptrend(), "AAPL": _df_uptrend(), "MSFT": _df_uptrend()},
        failed={},
    )
    spec = _minimal_spec()
    result = run_backtest(spec, db=MagicMock())
    assert isinstance(result, BacktestRunResult)
    assert result.is_metrics is not None
    assert result.oos_metrics is not None
    assert result.verdict is not None
    assert result.verdict.label in {
        "insufficient", "reject", "overfit", "weak",
        "underperform_bench", "positive_edge",
    }
    # Equity curves non-empty
    assert len(result.equity_curve_is) > 0
    assert len(result.equity_curve_oos) > 0


@patch("src.lab.backtest_runner.DataLoader")
@patch("src.lab.backtest_runner.load_universe_tickers")
def test_e2e_handles_empty_universe(mock_universe, mock_loader_cls):
    from src.lab.engine.universe import UniverseError
    mock_universe.side_effect = UniverseError("empty watchlist")
    spec = _minimal_spec()
    result = run_backtest(spec, db=MagicMock())
    assert result.error_message is not None
    assert "empty" in result.error_message.lower() or "universe" in result.error_message.lower()


@patch("src.lab.backtest_runner.run_simulation")
@patch("src.lab.backtest_runner.DataLoader")
@patch("src.lab.backtest_runner.load_universe_tickers")
def test_oos_simulation_and_metrics_use_same_starting_equity(universe, loader, simulation):
    from types import SimpleNamespace
    from src.lab.engine.data import DataLoadResult
    universe.return_value = ["AAPL"]
    loader.return_value.load.return_value = DataLoadResult(bars={"AAPL": _df_uptrend()}, failed={})
    simulation.side_effect = [
        SimpleNamespace(equity_curve=[100000, 120000], trades=[]),
        SimpleNamespace(equity_curve=[120000, 126000], trades=[]),
    ]
    spec = _minimal_spec()
    result = run_backtest(spec, db=MagicMock())
    assert simulation.call_args_list[1].args[0].backtest_config.starting_capital_usd == 120000
    assert abs(result.oos_metrics.total_return - 0.05) < 1e-9
    assert spec.backtest_config.starting_capital_usd == 100000


@patch('src.lab.backtest_runner._compute_benchmark_cagr', return_value=0.15)
@patch('src.lab.backtest_runner.DataLoader')
@patch('src.lab.backtest_runner.load_universe_tickers', return_value=['AAPL'])
def test_benchmark_uses_oos_dates(universe, loader, benchmark):
    from datetime import date
    from src.lab.engine.data import DataLoadResult
    spec = _minimal_spec()
    spec.backtest_config.start_date = '2020-01-01'
    spec.backtest_config.end_date = '2021-01-01'
    spec.backtest_config.benchmark = 'spy'
    loader.return_value.load.return_value = DataLoadResult(bars={'AAPL': _df_uptrend()}, failed={})
    result = run_backtest(spec, db=MagicMock())
    benchmark.assert_called_once_with(date.fromisoformat(result.midpoint_date), date(2021, 1, 1))
    assert result.benchmark_cagr == 0.15
