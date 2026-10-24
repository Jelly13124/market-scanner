"""Best-effort multi-period fundamentals for the report's trend charts.

The default hybrid provider (Finnhub) returns only a single current snapshot of
financial metrics, so the fundamental-trends + valuation-band charts have no
history to plot. yfinance annual income statements — exposed via the existing
``src.tools.line_items.search_line_items`` — DO carry ~5 annual periods, so we
pull them here and shape them into the duck-typed objects the chart renderers
expect (attributes: ``report_period``, ``gross_margin``, ``operating_margin``,
``net_margin``, ``revenue_growth``, ``price_to_earnings_ratio``).

Everything is best-effort: any failure returns ``[]`` (the chart renderers then
fall back to their "Insufficient history" placeholder, which the orchestrator
guards against emitting anyway).
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

logger = logging.getLogger(__name__)


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def fetch_fundamental_history(ticker: str, end_date: str, *, limit: int = 6) -> list:
    """Return newest-first period objects with margins + revenue growth (and a
    best-effort historical P/E). ``[]`` on any failure."""
    try:
        from src.tools.line_items import search_line_items
        items = search_line_items(
            ticker=ticker,
            line_items=[
                "revenue", "gross_profit", "operating_income",
                "net_income", "earnings_per_share",
            ],
            end_date=end_date, period="annual", limit=limit,
        )
    except Exception as e:
        logger.warning("fundamental history fetch failed for %s: %s", ticker, e)
        return []
    if not items:
        return []

    # Historical P/E = (price near each fiscal period end) / (annual basic EPS).
    # Isolated so a price-fetch failure never costs us the margin series.
    pe_at: dict[str, float | None] = {}
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period=f"{limit + 1}y", interval="1mo")
        if hist is not None and not hist.empty and "Close" in hist.columns:
            import pandas as pd
            closes = hist["Close"].dropna()
            for it in items:
                rp = getattr(it, "report_period", None)
                eps = _f(getattr(it, "earnings_per_share", None))
                if not rp or not eps:
                    continue
                try:
                    ts = pd.to_datetime(rp)
                    # nearest monthly close on/before the period end
                    prior = closes[closes.index <= ts.tz_localize(closes.index.tz)] \
                        if closes.index.tz is not None else closes[closes.index <= ts]
                    px = float(prior.iloc[-1]) if len(prior) else None
                    pe_at[rp] = (px / eps) if (px and eps) else None
                except Exception:
                    continue
    except Exception as e:
        logger.debug("P/E history fetch failed for %s: %s", ticker, e)

    out = []
    for i, it in enumerate(items):  # items are newest-first
        rev = _f(getattr(it, "revenue", None))
        gp = _f(getattr(it, "gross_profit", None))
        oi = _f(getattr(it, "operating_income", None))
        ni = _f(getattr(it, "net_income", None))
        prev_rev = _f(getattr(items[i + 1], "revenue", None)) if i + 1 < len(items) else None
        out.append(SimpleNamespace(
            report_period=getattr(it, "report_period", None),
            gross_margin=(gp / rev) if (gp is not None and rev) else None,
            operating_margin=(oi / rev) if (oi is not None and rev) else None,
            net_margin=(ni / rev) if (ni is not None and rev) else None,
            revenue_growth=(rev / prev_rev - 1.0) if (rev and prev_rev) else None,
            price_to_earnings_ratio=pe_at.get(getattr(it, "report_period", None)),
        ))
    return out
