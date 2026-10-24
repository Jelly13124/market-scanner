"""Sector relative-strength analyst.

For each ticker:
  1. Look up its GICS sector via the v2 hybrid client's CompanyFacts.
  2. Map the sector to a tracking SPDR sector ETF (XLK, XLV, etc.).
  3. Compute 20-trading-day return for both the ticker and its sector ETF.
  4. Relative strength = ticker_return − sector_etf_return.
  5. Emit signal:
        RS ≥ +3pp  → bullish  (outperforming sector → strong relative momentum)
        RS ≤ -3pp  → bearish  (lagging sector → weakness)
        else        → neutral
     Confidence scales with |RS|, capped at 80.

Caching:
  * Sector lookups cached per ticker (rarely change inside a single run).
  * Sector-ETF prices cached per (etf, scan_date) — multiple tickers in
    the same sector share the fetch.

Both caches are module-level + thread-safe — the workflow runs in
parallel branches but the v2 hybrid client is itself thread-safe.

NDX100 caveat: ~80% Technology → most tickers will be compared to XLK,
so this agent's contribution to ticker DIFFERENTIATION is limited on
NDX100. On SP500/Russell3000 it gains more signal.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta
from typing import Any

from langchain_core.messages import HumanMessage

from src.graph.state import AgentState, show_agent_reasoning
from src.utils.progress import progress

logger = logging.getLogger(__name__)


# GICS sector → SPDR sector ETF symbol. We use the SPDR Select Sector
# series because they're the standard institutional benchmark for sector
# relative strength.
#
# Includes both top-level GICS sectors (Technology / Health Care) AND
# Finnhub's industry-level labels (Semiconductors / Banking / etc.) since
# Finnhub's ``/stock/profile2`` populates the sector field with the more
# specific industry name about half the time. Maps each industry to its
# parent GICS sector's SPDR ETF.
_SECTOR_ETF: dict[str, str] = {
    # GICS sectors
    "Technology": "XLK",
    "Information Technology": "XLK",
    "Health Care": "XLV",
    "Healthcare": "XLV",
    "Financials": "XLF",
    "Financial Services": "XLF",
    "Consumer Discretionary": "XLY",
    "Consumer Cyclical": "XLY",
    "Consumer Staples": "XLP",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Basic Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
    "Telecommunication Services": "XLC",
    # Common Finnhub industry-level labels → parent GICS ETF
    "Semiconductors": "XLK",
    "Software": "XLK",
    "Software—Application": "XLK",
    "Software—Infrastructure": "XLK",
    "Hardware": "XLK",
    "Computer Hardware": "XLK",
    "Communications": "XLC",
    "Media": "XLC",
    "Telecommunication": "XLC",
    "Internet Content & Information": "XLC",
    "Banking": "XLF",
    "Banks": "XLF",
    "Insurance": "XLF",
    "Capital Markets": "XLF",
    "Asset Management": "XLF",
    "Biotechnology": "XLV",
    "Pharmaceuticals": "XLV",
    "Medical Devices": "XLV",
    "Health Care Services": "XLV",
    "Retail": "XLY",
    "Retail—Apparel & Specialty": "XLY",
    "Internet Retail": "XLY",
    "Automobiles": "XLY",
    "Auto Manufacturers": "XLY",
    "Restaurants": "XLY",
    "Food & Staples Retailing": "XLP",
    "Beverages": "XLP",
    "Food Products": "XLP",
    "Tobacco": "XLP",
    "Household Products": "XLP",
    "Oil & Gas": "XLE",
    "Oil, Gas & Consumable Fuels": "XLE",
    "Aerospace & Defense": "XLI",
    "Airlines": "XLI",
    "Logistics": "XLI",
    "Machinery": "XLI",
    "Building Products": "XLI",
    "Chemicals": "XLB",
    "Metals & Mining": "XLB",
    "Electric Utilities": "XLU",
    "REITs": "XLRE",
}
_FALLBACK_ETF = "SPY"

# RS thresholds in percentage points. ±3pp over 20d is roughly a 1σ move
# vs SPY-relative noise on individual NDX100 tickers.
_RS_BULL_PP = 0.03
_RS_BEAR_PP = -0.03


_SECTOR_CACHE_LOCK = threading.Lock()
_SECTOR_CACHE: dict[str, str | None] = {}  # ticker → sector (or None if unknown)
_ETF_PRICES_LOCK = threading.Lock()
_ETF_PRICES: dict[tuple[str, str], float | None] = {}  # (etf, scan_date) → 20d return


def _lookup_sector(ticker: str, provider_factory=None) -> str | None:
    """Cached GICS sector lookup via v2 hybrid client. None on any failure."""
    with _SECTOR_CACHE_LOCK:
        if ticker in _SECTOR_CACHE:
            return _SECTOR_CACHE[ticker]

    sector: str | None = None
    try:
        from v2.data.factory import get_provider_factory
        factory = provider_factory or get_provider_factory()
        client = factory()
        try:
            facts = client.get_company_facts(ticker)
            if facts is not None:
                sector = facts.sector
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
    except Exception as e:
        logger.debug("sector_agent: get_company_facts(%s) failed: %s", ticker, e)

    with _SECTOR_CACHE_LOCK:
        _SECTOR_CACHE[ticker] = sector
    return sector


def _twenty_day_return(symbol: str, scan_date: str, provider_factory=None) -> float | None:
    """Cached 20-trading-day return for a symbol ending at scan_date."""
    key = (symbol, scan_date)
    with _ETF_PRICES_LOCK:
        if key in _ETF_PRICES:
            return _ETF_PRICES[key]

    ret_20d: float | None = None
    try:
        from v2.data.factory import get_provider_factory
        factory = provider_factory or get_provider_factory()
        client = factory()
        try:
            end_dt = datetime.strptime(scan_date, "%Y-%m-%d").date()
            start_dt = end_dt - timedelta(days=45)  # buffer for ~30 trading days
            prices = client.get_prices(
                symbol, start_date=start_dt.isoformat(), end_date=scan_date,
            )
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        if prices and len(prices) >= 21:
            closes = [float(p.close) for p in sorted(prices, key=lambda p: p.time[:10])]
            tail21 = closes[-21:]
            ret_20d = (tail21[-1] / tail21[0]) - 1.0
    except Exception as e:
        logger.debug("sector_agent: 20d return for %s failed: %s", symbol, e)

    with _ETF_PRICES_LOCK:
        _ETF_PRICES[key] = ret_20d
    return ret_20d


def sector_agent(state: AgentState, agent_id: str = "sector_agent"):
    """Per-ticker sector relative-strength signal."""
    data = state["data"]
    tickers: list[str] = data.get("tickers") or []
    end_date: str = data.get("end_date") or ""

    analysis: dict[str, dict] = {}
    for ticker in tickers:
        progress.update_status(agent_id, ticker, "Looking up sector")
        sector = _lookup_sector(ticker)
        etf = _SECTOR_ETF.get(sector or "", _FALLBACK_ETF)

        progress.update_status(agent_id, ticker, "Computing relative strength")
        ticker_ret = _twenty_day_return(ticker, end_date)
        etf_ret = _twenty_day_return(etf, end_date)

        if ticker_ret is None or etf_ret is None:
            analysis[ticker] = {
                "signal": "neutral",
                "confidence": 0,
                "reasoning": (
                    f"Insufficient price data for {ticker} or {etf} "
                    f"to compute 20d relative strength."
                ),
                "metrics": {
                    "sector": sector,
                    "sector_etf": etf,
                    "ticker_return_20d": ticker_ret,
                    "etf_return_20d": etf_ret,
                    "relative_strength_pp": None,
                },
            }
            progress.update_status(agent_id, ticker, "Done (insufficient data)")
            continue

        rs = ticker_ret - etf_ret
        if rs >= _RS_BULL_PP:
            signal = "bullish"
        elif rs <= _RS_BEAR_PP:
            signal = "bearish"
        else:
            signal = "neutral"

        # |RS| → confidence. 3pp = floor (just over threshold), 15pp = ceiling.
        confidence = min(80, max(0, int(abs(rs) * 500)))
        if signal == "neutral":
            confidence = max(10, min(40, int(abs(rs) * 800)))

        sector_label = sector or "Unknown"
        reasoning = (
            f"{ticker} in {sector_label} (vs {etf}). 20d return "
            f"{ticker_ret * 100:+.1f}% vs {etf} {etf_ret * 100:+.1f}% "
            f"→ RS {rs * 100:+.1f}pp."
        )
        if etf == _FALLBACK_ETF and sector is None:
            reasoning += " (Sector unknown; compared to SPY as fallback.)"

        analysis[ticker] = {
            "signal": signal,
            "confidence": confidence,
            "reasoning": reasoning,
            "metrics": {
                "sector": sector,
                "sector_etf": etf,
                "ticker_return_20d": round(ticker_ret, 4),
                "etf_return_20d": round(etf_ret, 4),
                "relative_strength_pp": round(rs, 4),
            },
        }
        progress.update_status(agent_id, ticker, "Done")

    if state.get("metadata", {}).get("show_reasoning"):
        show_agent_reasoning(analysis, "Sector Agent")

    signals = data.setdefault("analyst_signals", {})
    signals[agent_id] = analysis

    message = HumanMessage(content=json.dumps(analysis), name=agent_id)
    progress.update_status(agent_id, None, "Done")
    return {"messages": [message], "data": data}
