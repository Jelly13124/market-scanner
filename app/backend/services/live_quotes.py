"""On-demand live market quotes for watchlist tickers.

US quotes use Finnhub with a bounded short-lived memory cache. The legacy
Yahoo path remains for A-share symbols. Quotes never use MongoDB.

``fetch_live_quotes`` is best-effort: it never raises. A failed batch or a
bad symbol yields rows with ``error`` set and ``None`` data fields, so the
UI can show "—" rather than blow up.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (ValueError, TypeError):
        return None
    # yfinance fills gaps with NaN — treat as missing.
    if f != f:  # NaN
        return None
    return f


def _to_int(value: Any) -> int | None:
    f = _to_float(value)
    if f is None:
        return None
    try:
        return int(f)
    except (ValueError, OverflowError):
        return None


def _frame_for(df: Any, ticker: str, *, single: bool):
    """Return the per-ticker OHLCV sub-frame, or None if absent.

    With ``group_by="ticker"`` and multiple symbols, columns are a
    MultiIndex keyed by ticker at the top level. With a single symbol,
    yfinance returns a plain (non-grouped) frame.
    """
    if single:
        return df
    # Multi-ticker: top-level column label is the ticker.
    try:
        if ticker in df.columns.get_level_values(0):
            return df[ticker]
    except (AttributeError, KeyError, TypeError):
        return None
    return None


def _row_from_frame(ticker: str, sub: Any) -> dict[str, Any]:
    """Extract a quote dict from a per-ticker OHLCV frame.

    ``Close`` is required to call it data; ``Open/High/Low/Volume`` come from
    the last row, ``prev_close`` from the prior available close.
    """
    empty = {
        "ticker": ticker,
        "price": None,
        "prev_close": None,
        "change_pct": None,
        "volume": None,
        "day_open": None,
        "day_high": None,
        "day_low": None,
        "error": "no data",
    }
    if sub is None:
        return empty

    try:
        closes = sub["Close"].dropna()
    except (KeyError, TypeError, AttributeError):
        return empty
    if len(closes) == 0:
        return empty

    price = _to_float(closes.iloc[-1])
    if price is None:
        return empty
    prev_close = _to_float(closes.iloc[-2]) if len(closes) >= 2 else None

    change_pct = None
    if prev_close:  # excludes None and 0.0
        change_pct = (price / prev_close - 1.0) * 100.0

    # Last row of the full frame for the day's OHLCV (may differ from the
    # last non-NaN close row, but the latest bar is what a live view wants).
    last = sub.iloc[-1]

    return {
        "ticker": ticker,
        "price": round(price, 4),
        "prev_close": round(prev_close, 4) if prev_close is not None else None,
        "change_pct": round(change_pct, 4) if change_pct is not None else None,
        "volume": _to_int(last.get("Volume")),
        "day_open": _to_float(last.get("Open")),
        "day_high": _to_float(last.get("High")),
        "day_low": _to_float(last.get("Low")),
        "error": None,
    }


def _fetch_yahoo_quotes(tickers: list[str]) -> list[dict]:
    """Fast batch live quotes for ``tickers`` (input order preserved).

    Best-effort: never raises. Empty/None input → ``[]``. A whole-batch
    failure → every ticker as a ``"no data"`` row. One bad symbol does not
    sink the batch (per-ticker extraction is isolated).
    """
    if not tickers:
        return []

    single = len(tickers) == 1

    try:
        import yfinance as yf

        df = yf.download(
            tickers,
            period="5d",
            interval="1d",
            auto_adjust=False,
            group_by="ticker",
            progress=False,
            threads=True,
        )
    except Exception as exc:  # noqa: BLE001 — best-effort, never propagate
        logger.warning("live quote batch download failed: %s", exc)
        df = None

    no_data = df is None or getattr(df, "empty", False)

    rows: list[dict] = []
    for ticker in tickers:
        if no_data:
            rows.append(_row_from_frame(ticker, None))
            continue
        try:
            sub = _frame_for(df, ticker, single=single)
            rows.append(_row_from_frame(ticker, sub))
        except Exception as exc:  # noqa: BLE001 — one bad symbol must not sink the batch
            logger.warning("live quote extraction failed for %s: %s", ticker, exc)
            rows.append(_row_from_frame(ticker, None))
    return rows


from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import os
from v2.data.finnhub_client import FinnhubClient
from v2.data.ashare.symbol import is_ashare

_QUOTE_CACHE = OrderedDict()
_QUOTE_LOCK = threading.Lock()


def fetch_live_quotes(tickers: list[str], *, finnhub_api_key: str | None = None, user_id: int | None = None) -> list[dict]:
    if not tickers:
        return []
    unique = list(dict.fromkeys(tickers))
    def fetch(ticker):
        cache_key = (user_id, ticker)
        now = time.monotonic()
        with _QUOTE_LOCK:
            cached = _QUOTE_CACHE.get(cache_key)
            if cached and cached[0] > now:
                return dict(cached[1])
        if is_ashare(ticker):
            row = _fetch_yahoo_quotes([ticker])[0]
            row['source'] = 'yahoo'
        else:
            row = _row_from_frame(ticker, None)
            row.update(source='finnhub', source_timestamp=None, received_at=None)
            try:
                with FinnhubClient(api_key=finnhub_api_key) as client:
                    quote = client.get_quote(ticker)
                    if quote is not None:
                        row.update(price=quote.current_price, prev_close=quote.prev_close, change_pct=quote.percent_change,
                            day_open=quote.day_open, day_high=quote.day_high, day_low=quote.day_low,
                            source_timestamp=quote.asof_timestamp, received_at=quote.received_at, error=None)
                    else:
                        row['error'] = getattr(client, 'last_status', 'no data')
            except Exception as error:
                logger.warning('Live quote unavailable for %s (%s)', ticker, type(error).__name__)
        if row['price'] is not None:
            with _QUOTE_LOCK:
                _QUOTE_CACHE[cache_key] = (time.monotonic() + max(1, int(os.getenv('QUOTE_CACHE_TTL_SECONDS', '15'))), dict(row))
                _QUOTE_CACHE.move_to_end(cache_key)
                while len(_QUOTE_CACHE) > 4096:
                    _QUOTE_CACHE.popitem(last=False)
        return row
    with ThreadPoolExecutor(max_workers=min(4, len(unique))) as pool:
        rows = dict(zip(unique, pool.map(fetch, unique)))
    return [dict(rows[ticker]) for ticker in tickers]
