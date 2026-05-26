"""v2 backtesting — replay the scanner over history, measure forward returns.

Public API:
    run_backtest(...)         programmatic backtest, returns CSV row count
    compute_forward_returns   per-(ticker, date) forward + alpha helper
    trading_days_between      list of ISO trading-day strings via SPY bars

CLI: ``python -m v2.backtesting.run --start ... --end ... --output ...``
"""

from v2.backtesting.engine import (
    CSV_COLUMNS,
    DEFAULT_WINDOWS,
    SKIP_FOR_BACKTEST,
    run_backtest,
)
from v2.backtesting.forward_returns import compute_forward_returns, direction_adjust
from v2.backtesting.trading_calendar import trading_days_between

__all__ = [
    "CSV_COLUMNS",
    "DEFAULT_WINDOWS",
    "SKIP_FOR_BACKTEST",
    "run_backtest",
    "compute_forward_returns",
    "direction_adjust",
    "trading_days_between",
]
