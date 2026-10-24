"""Daily OHLCV via mootdx (TDX market data).

mootdx is a pure-Python TDX client that connects to TCP servers maintained
by Tongdaxin. No API key required; servers are free. The library bundles a
fallback list and rotates on connection failure - we surface the final
exception to the caller (AShareClient catches and returns []).

API drift note (2026-05-26): the plan referenced mootdx 2.1.6, but the
environment ships 0.11.7. Differences relative to the plan:
  - `Quotes.factory(market='std')` still works.
  - `bars()` signature is now `(symbol, frequency, start, offset, **kwargs)`.
    There is no `market=` kwarg - mootdx auto-detects the market from the
    symbol via `get_stock_market()`. The plan's `n=n_bars` is now `offset`.
  - BSE codes (8xxxxx / 4xxxxx) return market=2 from get_stock_market, but
    we still early-return [] to match the documented v2 scope (mootdx
    routinely fails on BSE servers).
"""

from __future__ import annotations

import pandas as pd

from v2.data.models import Price

# Lazy module-level import inside try/except so non-A-share workflows
# don't break when the [ashare] extra is absent. Tests patch the `Quotes`
# symbol in this module's namespace, so the mock works whether or not
# mootdx is actually installed.
try:
    from mootdx.quotes import Quotes
except ImportError as e:
    Quotes = None  # type: ignore[assignment]
    _IMPORT_ERROR: ImportError | None = e
else:
    _IMPORT_ERROR = None


def _split_canonical(ticker: str) -> tuple[str, str]:
    """'600519.SH' -> ('600519', 'SH')."""
    code, exch = ticker.split('.', 1)
    return code, exch.upper()


def fetch_daily_ohlcv(
    canonical_ticker: str,
    start_date: str,
    end_date: str,
    *,
    n_bars: int = 800,
) -> list[Price]:
    """Fetch daily OHLCV for a canonical A-share ticker.

    Returns list[Price] sorted ascending by date, restricted to
    [start_date, end_date] inclusive. Returns [] for BSE tickers
    (v1 scope: SH/SZ only).
    """
    if Quotes is None:
        raise RuntimeError(
            "mootdx not installed - `pip install mootdx` or "
            "`poetry install --extras ashare`"
        ) from _IMPORT_ERROR

    code, exch = _split_canonical(canonical_ticker)
    if exch == 'BJ':
        # BSE not supported in v1; v2 will use Eastmoney
        return []

    client = Quotes.factory(market='std')
    # mootdx 0.11.7 `bars` signature: (symbol, frequency, start, offset).
    # frequency 9 = daily. mootdx returns latest `offset` bars (capped at
    # 800); we filter the result to the requested date window.
    df = client.bars(symbol=code, frequency=9, start=0, offset=n_bars)
    if df is None or len(df) == 0:
        return []
    return _df_to_prices(df, start_date, end_date)


def _df_to_prices(df: pd.DataFrame, start_date: str, end_date: str) -> list[Price]:
    """Convert mootdx DataFrame to list[Price], filtered to date window."""
    if 'date' not in df.columns:
        # some mootdx versions use 'datetime' or set index - normalize
        if 'datetime' in df.columns:
            df = df.rename(columns={'datetime': 'date'})
        elif df.index.name in ('date', 'datetime'):
            df = df.reset_index().rename(columns={df.index.name: 'date'})
    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    df = df[(df['date'] >= start_ts) & (df['date'] <= end_ts)]

    out: list[Price] = []
    for _, row in df.iterrows():
        vol_raw = row['vol'] if 'vol' in df.columns else row.get('volume', 0)
        out.append(Price(
            open=float(row['open']),
            high=float(row['high']),
            low=float(row['low']),
            close=float(row['close']),
            volume=int(vol_raw),
            time=row['date'].strftime('%Y-%m-%d'),
            adjusted_close=float(row['close']),  # mootdx daily already adjusted
        ))
    return out
