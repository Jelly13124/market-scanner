"""Per-ticker shared data bundle.

Each pipeline run fetches once via ``fetch_shared_data(ticker, scan_date)``
and passes the result to every module so the 10 modules don't each
re-fetch the same price/financial/news lists.

Cache is a module-level dict keyed on ``(ticker, scan_date)``. Lives for
the lifetime of the Python process. Cron runs spin up fresh processes
daily so this is effectively per-run caching.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SharedData:
    """All raw data needed by the analytical modules.

    Per-ticker bundle plus benchmark prices (SPY, sector ETF) needed by
    the macro and sector modules.
    """

    ticker: str
    scan_date: str
    prices: list                          # list[Price] from v2.data.models
    financials: list                      # list[FinancialMetrics]
    insider_trades: list                  # list[InsiderTrade]
    news: list                            # list[NewsArticle]
    analyst_actions: list                 # list[AnalystAction]
    analyst_targets: Any | None           # AnalystTargets or None
    earnings_history: list                # list[EarningsRecord]
    company_facts: dict
    sector_etf_prices: list               # benchmark for sector module
    spy_prices: list                      # benchmark for macro module


_CACHE: dict[tuple[str, str], SharedData] = {}
_LOCK = threading.Lock()


# Sector → SPDR ETF mapping for the sector module benchmark. Same table
# used by src/agents/sector_agent.py; kept duplicated here to keep
# src/research/ free of cross-dependency on the legacy agent layer.
_SECTOR_ETF = {
    "Technology": "XLK", "Information Technology": "XLK",
    "Health Care": "XLV", "Healthcare": "XLV", "Pharmaceuticals": "XLV",
    "Financials": "XLF", "Banking": "XLF",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Materials": "XLB",
    "Communication Services": "XLC",
    "Semiconductors": "XLK",
}


def _fetch_raw(ticker: str, scan_date: str) -> SharedData:
    """Hit the v2 data layer for every field. Best-effort: each subfetch
    is wrapped so a single source failing doesn't kill the whole bundle.
    """
    from v2.data.factory import get_provider_factory

    factory = get_provider_factory()
    client = factory()

    end_dt = datetime.strptime(scan_date, "%Y-%m-%d").date()
    start_dt = (end_dt - timedelta(days=400)).isoformat()  # ~1 year + buffer

    bundle = SharedData(
        ticker=ticker, scan_date=scan_date,
        prices=[], financials=[], insider_trades=[],
        news=[], analyst_actions=[], analyst_targets=None,
        earnings_history=[], company_facts={},
        sector_etf_prices=[], spy_prices=[],
    )

    try:
        bundle.prices = client.get_prices(ticker, start_dt, scan_date)
    except Exception as e:
        logger.warning("shared_data: prices(%s) failed: %s", ticker, e)
    try:
        bundle.financials = client.get_financial_metrics(ticker, scan_date)
    except Exception as e:
        logger.warning("shared_data: financials(%s) failed: %s", ticker, e)
    try:
        bundle.insider_trades = client.get_insider_trades(
            ticker, start_date=start_dt, end_date=scan_date, limit=200,
        )
    except Exception as e:
        logger.warning("shared_data: insider_trades(%s) failed: %s", ticker, e)
    try:
        bundle.news = client.get_news(
            ticker, start_date=start_dt, end_date=scan_date, limit=100,
        )
    except Exception as e:
        logger.warning("shared_data: news(%s) failed: %s", ticker, e)
    if hasattr(client, "get_analyst_actions"):
        try:
            bundle.analyst_actions = client.get_analyst_actions(
                ticker, end_date=scan_date, start_date=start_dt, limit=200,
            )
        except Exception as e:
            logger.warning("shared_data: analyst_actions(%s) failed: %s", ticker, e)
    if hasattr(client, "get_analyst_targets"):
        try:
            bundle.analyst_targets = client.get_analyst_targets(ticker, asof_date=scan_date)
        except Exception as e:
            logger.warning("shared_data: analyst_targets(%s) failed: %s", ticker, e)
    try:
        bundle.earnings_history = client.get_earnings_history(ticker, limit=12)
    except Exception as e:
        logger.warning("shared_data: earnings_history(%s) failed: %s", ticker, e)
    try:
        facts = client.get_company_facts(ticker)
        bundle.company_facts = facts.model_dump() if facts is not None else {}
    except Exception as e:
        logger.warning("shared_data: company_facts(%s) failed: %s", ticker, e)

    # Benchmarks
    sector = (bundle.company_facts.get("sector") or
              bundle.company_facts.get("industry") or "")
    etf = _SECTOR_ETF.get(sector)
    if etf:
        try:
            bundle.sector_etf_prices = client.get_prices(etf, start_dt, scan_date)
        except Exception as e:
            logger.warning("shared_data: sector_etf(%s)=%s failed: %s", ticker, etf, e)
    try:
        bundle.spy_prices = client.get_prices("SPY", start_dt, scan_date)
    except Exception as e:
        logger.warning("shared_data: spy_prices failed: %s", e)

    close = getattr(client, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass
    return bundle


def fetch_shared_data(ticker: str, scan_date: str) -> SharedData:
    """Cached fetch — returns the same SharedData instance for repeated
    calls with the same (ticker, scan_date) within a single process.
    """
    key = (ticker, scan_date)
    with _LOCK:
        hit = _CACHE.get(key)
    if hit is not None:
        return hit
    bundle = _fetch_raw(ticker, scan_date)
    with _LOCK:
        _CACHE[key] = bundle
    return bundle
