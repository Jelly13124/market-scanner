"""V1 ``src/tools/api.py`` — adapter on top of the v2 hybrid data client.

What changed (2026-05-18, plan §Phase B):
    Originally this module called the Financial Datasets API directly. After
    the FD paid tier started returning 402 on most endpoints, the v2 scanner
    moved to a hybrid composite client (EODHD prices+news, Finnhub
    insider+market-cap, yfinance earnings+analyst). The v1 agents kept calling
    FD though — which silently produced empty results, making every persona
    output "insufficient data".

    This rewrite keeps every public function's signature + return type
    identical (callers in ``src/agents/*.py`` and their tests are not
    touched), but internally:

      * Fetches via ``v2.data.composite_client.make_hybrid_client()`` —
        same source-of-truth the scanner uses.
      * Converts v2 model instances → v1 model instances (small adapter
        helpers ``_v1_*``); the field shapes are ~95% identical so this is
        mostly just constructor remapping.
      * ``search_line_items`` is delegated to a separate module that pulls
        from yfinance financial statements (the v2 client doesn't expose
        raw line items).
      * The existing ``_cache`` layer is preserved verbatim — agents still
        benefit from in-process caching across multiple LLM round-trips.
      * The ``api_key`` parameter is accepted but ignored — v2 clients read
        their own keys from .env.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import pandas as pd

from src.data.cache import get_cache
from src.data.models import (
    CompanyNews,
    CompanyNewsResponse,  # re-exported for tests that import it
    CompanyFactsResponse,  # re-exported for tests that import it
    FinancialMetrics,
    FinancialMetricsResponse,  # re-exported for tests that import it
    InsiderTrade,
    InsiderTradeResponse,  # re-exported for tests that import it
    LineItem,
    LineItemResponse,  # re-exported for tests that import it
    Price,
    PriceResponse,  # re-exported for tests that import it
)
from src.tools.line_items import search_line_items as _search_line_items_impl

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-process cache + v2 client singleton
# ---------------------------------------------------------------------------

# The cache layer is unchanged — agents call get_financial_metrics multiple
# times within a workflow and rely on hits across LLM round-trips. Keying
# semantics are identical to the pre-rewrite implementation.
_cache = get_cache()

# The v2 hybrid client owns thread pools, HTTP sessions and provider clients;
# constructing it is non-trivial. Build once per process, behind a lock so
# concurrent agent threads don't race the lazy init.
_v2_lock = threading.Lock()
_v2_client_cache: Any = None  # type: v2.data.composite_client.CompositeClient | None


def _get_v2_client():
    """Lazy thread-safe singleton for the v2 hybrid client."""
    global _v2_client_cache
    if _v2_client_cache is not None:
        return _v2_client_cache
    with _v2_lock:
        if _v2_client_cache is None:
            from v2.data.composite_client import make_hybrid_client
            _v2_client_cache = make_hybrid_client()
    return _v2_client_cache


# ---------------------------------------------------------------------------
# v2 → v1 model adapters
# ---------------------------------------------------------------------------

def _v1_price(v2: Any) -> Price:
    """v2.Price has an extra ``adjusted_close`` — v1 just drops it."""
    return Price(
        open=v2.open, close=v2.close, high=v2.high, low=v2.low,
        volume=v2.volume, time=v2.time,
    )


def _v1_financial_metrics(v2: Any) -> FinancialMetrics:
    """Field-by-field copy. v1 requires ``currency: str``; v2 sometimes
    omits it — default to USD when missing."""
    data = v2.model_dump()
    data.setdefault("currency", "USD")
    if data.get("currency") is None:
        data["currency"] = "USD"
    return FinancialMetrics(**data)


def _v1_insider_trade(v2: Any) -> InsiderTrade:
    """v1 has every field nullable except ``filing_date`` (which v2 also
    requires) — straight copy works."""
    return InsiderTrade(
        ticker=v2.ticker,
        issuer=v2.issuer,
        name=v2.name,
        title=v2.title,
        is_board_director=v2.is_board_director,
        transaction_date=v2.transaction_date,
        transaction_shares=v2.transaction_shares,
        transaction_price_per_share=v2.transaction_price_per_share,
        transaction_value=v2.transaction_value,
        shares_owned_before_transaction=v2.shares_owned_before_transaction,
        shares_owned_after_transaction=v2.shares_owned_after_transaction,
        security_title=v2.security_title,
        filing_date=v2.filing_date,
    )


def _v1_company_news(v2: Any) -> CompanyNews:
    """v1 requires ``source/date/url`` as ``str``; v2 has them nullable.
    Fall back to empty string so v1 model construction doesn't blow up."""
    return CompanyNews(
        ticker=v2.ticker,
        title=v2.title,
        author=None,  # v2 doesn't expose author
        source=v2.source or "",
        date=v2.date or "",
        url=v2.url or "",
        sentiment=v2.sentiment,  # str | None — same as v1
    )


# ---------------------------------------------------------------------------
# Public API — v1 signatures preserved exactly
# ---------------------------------------------------------------------------


def get_prices(
    ticker: str,
    start_date: str,
    end_date: str,
    api_key: str = None,  # accepted for signature compat; ignored
) -> list[Price]:
    """Fetch price bars for the window. Adjusted-close is dropped to match v1."""
    cache_key = f"{ticker}_{start_date}_{end_date}"
    if cached := _cache.get_prices(cache_key):
        return [Price(**p) for p in cached]

    try:
        client = _get_v2_client()
        v2_prices = client.get_prices(ticker, start_date, end_date)
    except Exception as e:
        logger.warning("v2 get_prices failed for %s: %s", ticker, e)
        return []
    if not v2_prices:
        return []

    out = [_v1_price(p) for p in v2_prices]
    _cache.set_prices(cache_key, [p.model_dump() for p in out])
    return out


def get_financial_metrics(
    ticker: str,
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    api_key: str = None,
) -> list[FinancialMetrics]:
    """Trailing financial-ratio snapshots."""
    cache_key = f"{ticker}_{period}_{end_date}_{limit}"
    if cached := _cache.get_financial_metrics(cache_key):
        return [FinancialMetrics(**m) for m in cached]

    try:
        client = _get_v2_client()
        v2_metrics = client.get_financial_metrics(ticker, end_date, period=period, limit=limit)
    except Exception as e:
        logger.warning("v2 get_financial_metrics failed for %s: %s", ticker, e)
        return []
    if not v2_metrics:
        return []

    out = []
    for m in v2_metrics:
        try:
            out.append(_v1_financial_metrics(m))
        except Exception as e:
            logger.debug("Skipping malformed metric for %s: %s", ticker, e)
    if not out:
        return []
    _cache.set_financial_metrics(cache_key, [m.model_dump() for m in out])
    return out


def search_line_items(
    ticker: str,
    line_items: list[str],
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    api_key: str = None,
) -> list[LineItem]:
    """Raw income/balance/cashflow line items per fiscal period.

    Backed by yfinance financial statements (see ``src/tools/line_items.py``);
    cherry-picks the requested fields per fiscal period, returning a list of
    v1 ``LineItem`` instances (one per period, with the requested fields
    populated as extra attributes).
    """
    return _search_line_items_impl(
        ticker=ticker, line_items=line_items, end_date=end_date,
        period=period, limit=limit, cache=_cache,
    )


def get_insider_trades(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    api_key: str = None,
) -> list[InsiderTrade]:
    """Insider transactions filed on or before ``end_date``."""
    cache_key = f"{ticker}_{start_date or 'none'}_{end_date}_{limit}"
    if cached := _cache.get_insider_trades(cache_key):
        return [InsiderTrade(**t) for t in cached]

    try:
        client = _get_v2_client()
        v2_trades = client.get_insider_trades(
            ticker, end_date, start_date=start_date, limit=limit,
        )
    except Exception as e:
        logger.warning("v2 get_insider_trades failed for %s: %s", ticker, e)
        return []
    if not v2_trades:
        return []

    out = []
    for t in v2_trades:
        try:
            out.append(_v1_insider_trade(t))
        except Exception as e:
            logger.debug("Skipping malformed insider trade for %s: %s", ticker, e)
    if not out:
        return []
    _cache.set_insider_trades(cache_key, [t.model_dump() for t in out])
    return out


def get_company_news(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    api_key: str = None,
) -> list[CompanyNews]:
    """News articles on or before ``end_date``."""
    cache_key = f"{ticker}_{start_date or 'none'}_{end_date}_{limit}"
    if cached := _cache.get_company_news(cache_key):
        return [CompanyNews(**n) for n in cached]

    try:
        client = _get_v2_client()
        v2_news = client.get_news(ticker, end_date, start_date=start_date, limit=limit)
    except Exception as e:
        logger.warning("v2 get_news failed for %s: %s", ticker, e)
        return []
    if not v2_news:
        return []

    out = []
    for n in v2_news:
        try:
            out.append(_v1_company_news(n))
        except Exception as e:
            logger.debug("Skipping malformed news article for %s: %s", ticker, e)
    if not out:
        return []
    _cache.set_company_news(cache_key, [n.model_dump() for n in out])
    return out


def get_market_cap(
    ticker: str,
    end_date: str,
    api_key: str = None,
) -> float | None:
    """Market cap. v2 has a dedicated endpoint that does the same date logic
    (today vs historical) we used to do here."""
    try:
        client = _get_v2_client()
        return client.get_market_cap(ticker, end_date)
    except Exception as e:
        logger.warning("v2 get_market_cap failed for %s: %s", ticker, e)
        return None


def prices_to_df(prices: list[Price]) -> pd.DataFrame:
    """Convert prices to a DataFrame. Pure utility — no API call."""
    if not prices:
        return pd.DataFrame()
    df = pd.DataFrame([p.model_dump() for p in prices])
    df["Date"] = pd.to_datetime(df["time"])
    df.set_index("Date", inplace=True)
    for col in ("open", "close", "high", "low", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.sort_index(inplace=True)
    return df


def get_price_data(ticker: str, start_date: str, end_date: str, api_key: str = None) -> pd.DataFrame:
    prices = get_prices(ticker, start_date, end_date, api_key=api_key)
    return prices_to_df(prices)
