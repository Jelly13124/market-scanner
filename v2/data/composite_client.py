"""Composite ``DataClient`` — routes each Protocol method to a configured backend.

The motivating use case: EODHD's $20 plan gives us prices + news (with daily
aggregate sentiment) but blocks insider/earnings/fundamentals. Finnhub's free
tier covers exactly the blocked endpoints. Combining them gives us **all four
scanner detectors fully working at $20/month**.

Usage::

    from v2.data import make_hybrid_client
    client = make_hybrid_client()    # EODHD prices+news, Finnhub everything else
    runner.run_scan(..., provider_factory=make_hybrid_client)
"""

from __future__ import annotations

import logging
from typing import Any

from v2.data.ashare.symbol import is_ashare as _is_ashare
from v2.data.client import FDClient
from v2.data.eodhd_client import EODHDClient
from v2.data.finnhub_client import FinnhubClient
from v2.data.models import (
    AnalystAction,
    AnalystTarget,
    EstimateRevisions,
    CompanyFacts,
    CompanyNews,
    Earnings,
    EarningsCalendarEntry,
    EarningsRecord,
    FinancialMetrics,
    InsiderTrade,
    Price,
    Quote,
)
from v2.data.protocol import DataClient

logger = logging.getLogger(__name__)


class CompositeClient:
    """Routes each ``DataClient`` method to a configured backend.

    All ``*_backend`` constructor args must satisfy the ``DataClient`` Protocol.
    Multiple slots may point at the same instance — ``close()`` is idempotent
    (closes each unique backend once).
    """

    def __init__(
        self,
        *,
        prices_backend: DataClient,
        news_backend: DataClient,
        insider_backend: DataClient,
        earnings_backend: DataClient,
        facts_backend: DataClient,
        metrics_backend: DataClient,
        analyst_backend: DataClient | None = None,
        quotes_backend: DataClient | None = None,
        calendar_backend: DataClient | None = None,
        ashare_backend: DataClient | None = None,
    ) -> None:
        self._prices = prices_backend
        self._news = news_backend
        self._insider = insider_backend
        self._earnings = earnings_backend
        self._facts = facts_backend
        self._metrics = metrics_backend
        # Optional — only present when a hybrid includes a yfinance-style
        # analyst source. Detectors should check ``hasattr(client,
        # 'get_analyst_targets')`` before calling.
        self._analyst = analyst_backend
        # Optional — only present when a hybrid has a backend that supports
        # the live ``/quote`` endpoint (currently Finnhub only). Callers
        # should check ``hasattr(client, 'get_quote')`` before using.
        self._quotes = quotes_backend
        # Optional — forward-looking earnings calendar. Defaults to the
        # earnings_backend for back-compat, but kept separate so we can
        # route per-ticker earnings history to one provider (yfinance — has
        # full trailing-quarter coverage) and bulk forward calendar to
        # another (Finnhub — has the /calendar/earnings endpoint).
        self._calendar = calendar_backend or earnings_backend
        # Optional — when set, ticker-keyed methods that receive an A-share
        # ticker (matched by ``v2.data.ashare.symbol.is_ashare``) dispatch
        # to this backend instead of the configured US slot. When None,
        # routing is unchanged from US-only behavior.
        self._ashare = ashare_backend

    def __enter__(self) -> CompositeClient:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def close(self) -> None:
        """Close each unique backend exactly once."""
        seen: set[int] = set()
        backends = [
            self._prices, self._news, self._insider,
            self._earnings, self._facts, self._metrics,
            self._calendar,
        ]
        if self._analyst is not None:
            backends.append(self._analyst)
        if self._quotes is not None:
            backends.append(self._quotes)
        if self._ashare is not None:
            backends.append(self._ashare)
        for backend in backends:
            if id(backend) in seen:
                continue
            seen.add(id(backend))
            closer = getattr(backend, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception as e:
                    logger.debug("Backend close raised: %s", e)

    # ------------------------------------------------------------------
    # DataClient Protocol — pure delegation
    # ------------------------------------------------------------------

    def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        **kwargs: Any,
    ) -> list[Price]:
        if self._ashare is not None and _is_ashare(ticker):
            return self._ashare.get_prices(ticker, start_date, end_date, **kwargs)
        return self._prices.get_prices(ticker, start_date, end_date, **kwargs)

    def get_news(
        self,
        ticker: str,
        end_date: str,
        start_date: str | None = None,
        limit: int = 1000,
    ) -> list[CompanyNews]:
        if self._ashare is not None and _is_ashare(ticker):
            return self._ashare.get_news(ticker, end_date, start_date, limit)
        return self._news.get_news(ticker, end_date, start_date, limit)

    def get_insider_trades(
        self,
        ticker: str,
        end_date: str,
        start_date: str | None = None,
        limit: int = 1000,
    ) -> list[InsiderTrade]:
        if self._ashare is not None and _is_ashare(ticker):
            return self._ashare.get_insider_trades(ticker, end_date, start_date, limit)
        return self._insider.get_insider_trades(ticker, end_date, start_date, limit)

    def get_earnings(self, ticker: str) -> Earnings | None:
        if self._ashare is not None and _is_ashare(ticker):
            return self._ashare.get_earnings(ticker)
        return self._earnings.get_earnings(ticker)

    def get_earnings_history(
        self,
        ticker: str,
        limit: int = 12,
    ) -> list[EarningsRecord]:
        if self._ashare is not None and _is_ashare(ticker):
            return self._ashare.get_earnings_history(ticker, limit)
        return self._earnings.get_earnings_history(ticker, limit)

    def get_earnings_calendar(
        self,
        *,
        start_date: str,
        end_date: str,
    ) -> list[EarningsCalendarEntry]:
        if not hasattr(self._calendar, "get_earnings_calendar"):
            return []
        return self._calendar.get_earnings_calendar(
            start_date=start_date, end_date=end_date,
        )

    def get_company_facts(self, ticker: str) -> CompanyFacts | None:
        if self._ashare is not None and _is_ashare(ticker):
            return self._ashare.get_company_facts(ticker)
        return self._facts.get_company_facts(ticker)

    def get_market_cap(self, ticker: str, end_date: str) -> float | None:
        if self._ashare is not None and _is_ashare(ticker):
            return self._ashare.get_market_cap(ticker, end_date)
        return self._facts.get_market_cap(ticker, end_date)

    def get_financial_metrics(
        self,
        ticker: str,
        end_date: str,
        period: str = "ttm",
        limit: int = 10,
    ) -> list[FinancialMetrics]:
        if self._ashare is not None and _is_ashare(ticker):
            return self._ashare.get_financial_metrics(ticker, end_date, period, limit)
        return self._metrics.get_financial_metrics(ticker, end_date, period, limit)

    # ------------------------------------------------------------------
    # AnalystDataClient methods — only available when analyst_backend is set
    # ------------------------------------------------------------------

    def get_analyst_targets(
        self,
        ticker: str,
        *,
        asof_date: str | None = None,
    ) -> AnalystTarget | None:
        if self._analyst is None:
            return None
        return self._analyst.get_analyst_targets(ticker, asof_date=asof_date)

    def get_analyst_actions(
        self,
        ticker: str,
        *,
        end_date: str,
        start_date: str,
        limit: int = 100,
    ) -> list[AnalystAction]:
        if self._analyst is None:
            return []
        return self._analyst.get_analyst_actions(
            ticker, end_date=end_date, start_date=start_date, limit=limit,
        )

    def get_estimate_revisions(
        self,
        ticker: str,
        *,
        period: str = "0q",
        asof_date: str | None = None,
    ) -> EstimateRevisions | None:
        # Routes through the same analyst_backend slot — yfinance delivers
        # both rating actions and EPS estimate revisions, no need for a
        # separate backend slot.
        if self._analyst is None or not hasattr(self._analyst, "get_estimate_revisions"):
            return None
        return self._analyst.get_estimate_revisions(
            ticker, period=period, asof_date=asof_date,
        )

    # ------------------------------------------------------------------
    # Live quote — only available when quotes_backend is set
    # ------------------------------------------------------------------

    def get_quote(self, ticker: str) -> Quote | None:
        if self._quotes is None:
            return None
        return self._quotes.get_quote(ticker)


# ----------------------------------------------------------------------
# Convenience builder for the recommended EODHD + Finnhub hybrid.
# ----------------------------------------------------------------------


def _has_eodhd_key() -> bool:
    """True iff EODHD_API_KEY env is set and non-empty. Used by
    make_hybrid_client to auto-degrade to a free tier when the user
    hasn't paid for EODHD."""
    import os
    return bool(os.environ.get("EODHD_API_KEY", "").strip())


def make_hybrid_client(
    *,
    include_ashare: bool = True,
    tier: str | None = None,
) -> CompositeClient:
    """Build a CompositeClient. Tier auto-detects from EODHD_API_KEY env:

    ``tier='paid'`` (EODHD key present) — recommended $20 hybrid:
        prices    -> EODHD (daily OHLCV, multi-year)
        news      -> EODHD (articles + daily aggregate sentiment overlay)

    ``tier='free'`` (no EODHD key) — degrades to Finnhub-only for prices/news:
        prices    -> Finnhub (/stock/candle, ~12mo history on free tier)
        news      -> Finnhub (/company-news, last 7-30d on free tier)

    Both tiers share the rest of the routing:
        insider   -> Finnhub (/stock/insider-transactions)
        earnings  -> yfinance (Ticker.get_earnings_dates — trailing 25 quarters)
        calendar  -> Finnhub (/calendar/earnings — forward-looking)
        facts     -> Finnhub (/stock/profile2)
        metrics   -> Finnhub (/stock/metric)
        analyst   -> yfinance (Ticker.analyst_price_targets)
        quotes    -> Finnhub (/quote)
        ashare    -> AShareClient (mootdx + Eastmoney + CLS — when ticker is
                     A-share). Set ``include_ashare=False`` to disable.

    Pass ``tier='paid'`` or ``tier='free'`` to override the auto-detect.
    """
    from v2.data.yfinance_client import YFinanceClient
    if tier is None:
        tier = "paid" if _has_eodhd_key() else "free"

    finnhub = FinnhubClient()
    yfin = YFinanceClient()

    if tier == "paid":
        eodhd = EODHDClient()
        prices_backend: DataClient = eodhd
        news_backend: DataClient = eodhd
    else:
        # Free tier: Finnhub does double duty for prices + news.
        prices_backend = finnhub
        news_backend = finnhub

    ashare: DataClient | None = None
    if include_ashare:
        try:
            from v2.data.ashare.client import AShareClient
            ashare = AShareClient()
        except ImportError:
            # Optional deps (mootdx etc.) not installed — degrade gracefully.
            ashare = None
    return CompositeClient(
        prices_backend=prices_backend,
        news_backend=news_backend,
        insider_backend=finnhub,
        # Earnings history → yfinance (trailing quarters); forward calendar
        # → Finnhub (different endpoint, different shape). Both are reused
        # backend instances — close() dedupes by id().
        earnings_backend=yfin,
        calendar_backend=finnhub,
        facts_backend=finnhub,
        metrics_backend=finnhub,
        analyst_backend=yfin,
        # Quote backend = same Finnhub instance.
        quotes_backend=finnhub,
        ashare_backend=ashare,
    )


def get_active_tier() -> str:
    """Return 'paid' or 'free' — the tier make_hybrid_client() will use
    under the current env. Surfaced to the frontend via a /tier endpoint
    so users can see what data source they're hitting."""
    return "paid" if _has_eodhd_key() else "free"
