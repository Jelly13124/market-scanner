"""Forward-return + market-relative alpha computation for backtest replay.

For each scanner pick (ticker, scan_date), we want to know "what did this
ticker do over the next N trading days, both raw and vs the benchmark."
That's the load-bearing question every detector ROI claim depends on.

Design decisions:

  * **Trading-day count is measured on the ticker's own bars**, not a
    synthetic calendar — handles ticker-specific halts/illiquidity
    naturally, and aligns with how the rest of v2 indexes price history.
  * **adjusted_close** is preferred over raw close so ex-dividend and
    split days don't produce phantom drops in forward returns.
  * **Simple returns** (P_t+N / P_t − 1), not log returns — matches the
    severity-z conventions used elsewhere in the scanner.
  * **Benchmark prices are passed in** by the caller (fetched ONCE for
    the whole backtest in ``engine.py``) rather than refetched per
    ticker. With 250 trading days × 100 tickers we'd otherwise pull SPY
    25k times.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable

from v2.data.models import Price
from v2.data.protocol import DataClient


def _parse_date(s: str) -> date | None:
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _close(p: Price) -> float | None:
    if p.adjusted_close is not None:
        return float(p.adjusted_close)
    if p.close is not None:
        return float(p.close)
    return None


def _windowed_return(
    bars: list[Price], scan_date_iso: str, n_days_forward: int,
) -> tuple[float | None, float | None]:
    """Given an oldest→newest list of bars covering both the scan_date and
    forward window, return (close_at_scan, return_n_days_forward). Returns
    (None, None) when the scan_date bar is missing; returns (close, None)
    when the forward window extends past available data.

    "n trading days forward" is interpreted on the ticker's own bars: the
    Nth bar AFTER the scan_date bar (index +N).
    """
    if not bars:
        return None, None

    # Find the index of the scan_date bar. Bars are oldest→newest; binary
    # search isn't worth it for ~70-bar windows — linear is fine.
    scan_idx = -1
    for i, p in enumerate(bars):
        if p.time[:10] == scan_date_iso:
            scan_idx = i
            break

    if scan_idx < 0:
        # No bar exactly at scan_date — pick the LAST bar on or before it.
        # Common when scan_date falls on a non-trading day.
        for i in range(len(bars) - 1, -1, -1):
            if bars[i].time[:10] <= scan_date_iso:
                scan_idx = i
                break

    if scan_idx < 0:
        return None, None

    scan_close = _close(bars[scan_idx])
    if scan_close is None or scan_close <= 0:
        return None, None

    forward_idx = scan_idx + n_days_forward
    if forward_idx >= len(bars):
        # Forward window exceeds available data — common for scan_dates
        # close to today or short-history tickers.
        return scan_close, None

    forward_close = _close(bars[forward_idx])
    if forward_close is None or forward_close <= 0:
        return scan_close, None

    return scan_close, (forward_close / scan_close) - 1.0


def compute_forward_returns(
    fd: DataClient,
    *,
    ticker: str,
    scan_date: str,
    windows: Iterable[int] = (1, 5, 20, 63),
    benchmark_ticker: str = "SPY",
    benchmark_prices: list[Price] | None = None,
) -> dict[str, float | None]:
    """Compute forward returns + benchmark-relative alpha for one
    (ticker, scan_date) pair across multiple horizons.

    Returns a dict with these keys per window N in ``windows``:

        ret_Nd        ticker's simple return over N trading days forward
        bench_ret_Nd  benchmark's simple return over the same window
        alpha_Nd      ret_Nd − bench_ret_Nd (None if either leg missing)

    Plus:

        close_at_scan ticker's close on the scan_date (None if no bar)

    Missing data (forward window exceeds price history) yields None for
    the affected column rather than truncating the dict — callers can
    write the row and skip missing windows in aggregation.

    ``benchmark_prices`` should be pre-fetched ONCE per backtest by the
    engine layer (the same series is reused for every ticker × scan_date
    combination); passing None falls back to a per-call fetch which is
    fine for unit tests but quadratic in production.
    """
    windows = tuple(windows)
    if not windows:
        return {"close_at_scan": None}

    scan_d = _parse_date(scan_date)
    if scan_d is None:
        return {"close_at_scan": None}

    # Fetch enough forward bars to cover the longest window plus weekend/
    # holiday padding. 1.6× converts trading days to calendar days
    # generously (same heuristic used in event_study and detectors).
    max_window = max(windows)
    fetch_end = (scan_d + timedelta(days=int(max_window * 1.6) + 7)).isoformat()
    bars = fd.get_prices(ticker, scan_date, fetch_end)
    bars_sorted = sorted(bars, key=lambda p: p.time[:10]) if bars else []

    bench_bars: list[Price] = []
    if benchmark_prices is not None:
        # Trust caller-provided series; assume already sorted but be defensive.
        bench_bars = sorted(benchmark_prices, key=lambda p: p.time[:10])
    else:
        fetched = fd.get_prices(benchmark_ticker, scan_date, fetch_end)
        if fetched:
            bench_bars = sorted(fetched, key=lambda p: p.time[:10])

    out: dict[str, float | None] = {"close_at_scan": None}

    for n in windows:
        scan_close, ticker_ret = _windowed_return(bars_sorted, scan_date, n)
        _, bench_ret = _windowed_return(bench_bars, scan_date, n)
        # close_at_scan picks up the first non-None from any window
        if out["close_at_scan"] is None and scan_close is not None:
            out["close_at_scan"] = float(scan_close)
        out[f"ret_{n}d"] = ticker_ret
        out[f"bench_ret_{n}d"] = bench_ret
        if ticker_ret is not None and bench_ret is not None:
            out[f"alpha_{n}d"] = ticker_ret - bench_ret
        else:
            out[f"alpha_{n}d"] = None

    return out


def direction_adjust(value: float | None, direction: str) -> float | None:
    """Flip the sign of a return for short positions.

    Convention:
      * ``bullish``  → long, return as-is
      * ``bearish``  → short, flip sign
      * ``neutral``  → treat as long (raw return); caller may choose to
        exclude neutrals from aggregations.
    """
    if value is None:
        return None
    if direction == "bearish":
        return -value
    return value
