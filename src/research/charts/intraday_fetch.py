"""Intraday OHLCV fetch for the SOP Technical section's 5-min K-line.

Phase 10 Wave 2. The daily/weekly charts reuse ``shared.prices`` (daily
bars already fetched by the shared-data layer); intraday bars are not in
that payload, so this module pulls them on demand from yfinance.

``fetch_intraday_prices`` is **best-effort**: yfinance intraday only
covers the most recent days for US tickers and not at all for many
non-US / illiquid names. On any failure (network, rate-limit, empty
frame, non-US ticker) it returns ``[]`` and never raises — the renderer
downstream turns an empty list into a "No data" placeholder PNG.
"""

from __future__ import annotations

import logging

from v2.data.models import Price

logger = logging.getLogger(__name__)


def fetch_intraday_prices(
    ticker: str,
    *,
    period: str = "5d",
    interval: str = "5m",
) -> list[Price]:
    """Fetch intraday OHLCV bars for ``ticker`` via yfinance.

    ``period`` / ``interval`` map straight to ``yf.Ticker(...).history``.
    Returns a list of :class:`Price` (``time`` = the bar's index timestamp
    as ISO 8601). Best-effort: returns ``[]`` on any error or empty frame.
    """
    try:
        import yfinance as yf

        frame = yf.Ticker(ticker).history(period=period, interval=interval)
        if frame is None or frame.empty:
            logger.debug("intraday fetch empty for %s (%s/%s)", ticker, period, interval)
            return []

        prices: list[Price] = []
        for ts, row in frame.iterrows():
            try:
                prices.append(
                    Price(
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=int(row["Volume"]),
                        time=ts.isoformat(),
                    )
                )
            except (KeyError, TypeError, ValueError):
                # Skip a malformed/NaN row rather than failing the whole fetch.
                continue
        return prices
    except Exception as e:  # noqa: BLE001 — best-effort, never raise
        logger.warning("intraday fetch failed for %s (%s/%s): %s", ticker, period, interval, e)
        return []
