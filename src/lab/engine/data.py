"""Phase 6B: batch OHLCV loader for the backtest engine.

Iterates tickers, calls v2/data fetch_prices for each, wraps any
failures in DataLoadResult.failed so the engine can keep running on
the remaining good tickers. Output: dict[ticker → pd.DataFrame] with
DatetimeIndex + OHLCV columns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

# Reuse Phase 1-5 data layer: composite client (EODHD → yfinance → Finnhub)
from src.tools.api import get_prices as fetch_prices

logger = logging.getLogger(__name__)


@dataclass
class DataLoadResult:
    bars: dict[str, pd.DataFrame] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)  # ticker → error reason


class DataLoader:
    """Sequential per-ticker batch loader. v1 is simple loop; multiprocess
    could be a v2 optimization if 500-ticker SP500 fetch is too slow."""

    def load(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
    ) -> DataLoadResult:
        result = DataLoadResult()
        start_iso = start_date.isoformat()
        end_iso = end_date.isoformat()
        for ticker in tickers:
            try:
                raw = fetch_prices(
                    ticker, start_date=start_iso, end_date=end_iso,
                )
            except Exception as e:
                logger.warning("DataLoader: %s failed: %s", ticker, e)
                result.failed[ticker] = f"{type(e).__name__}: {e}"
                continue
            if not raw:
                result.failed[ticker] = "no bars returned"
                continue
            df = _bars_to_dataframe(raw)
            if df.empty:
                result.failed[ticker] = "empty dataframe after parse"
                continue
            result.bars[ticker] = df
        return result


def _bars_to_dataframe(raw: list) -> pd.DataFrame:
    """Convert list of bar dicts (or model objects) to a DataFrame."""
    rows = []
    for b in raw:
        if hasattr(b, "model_dump"):
            d = b.model_dump()
        elif isinstance(b, dict):
            d = b
        else:
            d = {k: getattr(b, k, None) for k in ("time", "open", "high", "low", "close", "volume")}
        rows.append(d)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["time"] = pd.to_datetime(df["time"])
    df = df.set_index("time").sort_index()
    # Ensure float columns
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close"])
    return df
