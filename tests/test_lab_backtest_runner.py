"""Phase 6E: end-to-end backtest_runner ties all engine pieces together."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

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


def test_saved_volume_spike_keeps_its_current_bar_in_the_average():
    from src.lab.engine.indicators import compute_indicators
    from src.lab.engine.signal_eval import eval_entry

    saved = _minimal_spec().model_dump()
    saved["entry"]["signals"] = [{"type": "volume_spike", "avg_period": 2, "multiplier": 2}]
    spec = StrategySpec.model_validate(saved)
    data = _df_uptrend(n=3)
    data["volume"] = [100, 100, 200]
    matches = eval_entry(spec.entry.signals[0], "AAPL", compute_indicators({"AAPL": data}))
    assert not matches.any()


def test_unavailable_relative_strength_does_not_close_an_or_group_position(monkeypatch):
    from types import SimpleNamespace

    data = _df_uptrend(n=12)
    data["adjusted_close"] = [100, 100, 120] + [110] * 9
    def historical_prices(ticker, start_date, end_date):
        frame = data.loc[start_date:end_date]
        if ticker == "SPY":
            return []
        return frame.rename_axis("time").reset_index().to_dict("records")

    monkeypatch.setattr("src.lab.backtest_runner.load_universe_tickers", lambda *a, **kw: ["NVDA"])
    monkeypatch.setattr("v2.data.factory.make_data_client", lambda: SimpleNamespace(get_prices=historical_prices))
    saved = _minimal_spec().model_dump()
    saved["entry"] = {"combiner": "or", "signals": [
        {"type": "range_breakout", "window": 2}, {"type": "relative_strength", "window": 2},
    ]}
    saved["exit"] = [{"type": "time_stop", "bars": 2}]
    saved["backtest_config"].update(start_date="2020-01-03", end_date="2020-01-18")
    result = run_backtest(StrategySpec.model_validate(saved), db=MagicMock())
    trade, = result.is_trades
    assert (trade["entry_date"][:10], trade["exit_date"][:10], trade["exit_reason"]) == (
        "2020-01-06", "2020-01-09", "time_stop",
    )


def test_daily_loader_distinguishes_absent_and_invalid_adjusted_prices():
    from datetime import date
    from src.lab.engine.data import DataLoader
    from src.lab.engine.signal_eval import iter_daily_rule_evidence
    from v2.data.models import Price
    from v2.rules.spec import RangeBreakoutRule

    prices = [
        Price(time=f"2024-03-0{i}", open=100, high=100, low=100, close=100, volume=10,
              adjusted_close=adj)
        for i, adj in enumerate([None, 105, float("nan"), None], start=1)
    ]
    result = DataLoader().load(["NVDA"], date(2024, 3, 1), date(2024, 3, 4),
                               daily_price_source=lambda *args, **kw: prices)
    outcomes = [trigger for _, trigger in iter_daily_rule_evidence(
        RangeBreakoutRule(window=1), result.bars["NVDA"],
    )]
    assert outcomes[0] is None
    assert outcomes[1].direction == "bullish"
    assert outcomes[2:] == [None, None]


@pytest.mark.parametrize(
    ("adjustment", "entry_dates"),
    [(None, []), (15.0, []), (9.0, ["2020-01-07"])],
)
def test_invalid_execution_bar_still_counts_in_breakout_history(monkeypatch, adjustment, entry_dates):
    from types import SimpleNamespace

    data = _df_uptrend(n=12)
    data["close"] = [10, 11, float("nan")] + [12] * 9
    data["adjusted_close"] = pd.Series([None, None, adjustment] + [None] * 9,
                                       index=data.index, dtype=object)
    def historical_prices(ticker, start_date, end_date):
        return data.loc[start_date:end_date].rename_axis("time").reset_index().to_dict("records")

    monkeypatch.setattr("src.lab.backtest_runner.load_universe_tickers", lambda *a, **kw: ["NVDA"])
    monkeypatch.setattr("v2.data.factory.make_data_client", lambda: SimpleNamespace(get_prices=historical_prices))
    saved = _minimal_spec().model_dump()
    saved["entry"]["signals"] = [{"type": "range_breakout", "window": 2}]
    saved["exit"] = [{"type": "time_stop", "bars": 1}]
    saved["backtest_config"].update(start_date="2020-01-01", end_date="2020-01-22",
                                   reverse_signal_as_exit=False)
    result = run_backtest(StrategySpec.model_validate(saved), db=MagicMock())
    assert [t["entry_date"][:10] for t in result.is_trades] == entry_dates
    assert len(result.equity_curve_is) == 9  # 10 sessions in the segment, one untradable close


def test_warmup_and_exclusive_end_alone_do_not_produce_a_backtest(monkeypatch):
    from types import SimpleNamespace

    data = _df_uptrend(2)
    data.index = pd.to_datetime(["2020-01-03", "2020-01-17"])
    def historical_prices(ticker, start_date, end_date):
        return data.loc[start_date:end_date].rename_axis("time").reset_index().to_dict("records")

    monkeypatch.setattr("src.lab.backtest_runner.load_universe_tickers", lambda *a, **kw: ["NVDA"])
    monkeypatch.setattr("v2.data.factory.make_data_client", lambda: SimpleNamespace(get_prices=historical_prices))
    saved = _minimal_spec().model_dump()
    saved["entry"]["signals"] = [{"type": "relative_volume", "window": 1}]
    saved["backtest_config"].update(start_date="2020-01-06", end_date="2020-01-17")
    result = run_backtest(StrategySpec.model_validate(saved), db=MagicMock())
    assert result.error_message
    assert result.is_metrics is None and result.oos_metrics is None
