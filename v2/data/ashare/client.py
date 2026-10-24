"""AShareClient - implements DataClient Protocol for China A-shares.

Backed by mootdx (OHLCV) + Eastmoney (fundamentals/earnings/market_cap)
+ CLS (cailianpress) news HTTP APIs. All free, no auth required.

Per the Protocol invariant, no method raises - failures degrade to
empty list / None. Per-instance requests.Session; not thread-safe
across threads - instantiate one per worker.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import requests

from v2.data.ashare.symbol import is_ashare, normalize
from v2.data.models import (
    CompanyFacts,
    CompanyNews,
    EarningsRecord,
    FinancialMetrics,
    Price,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class AShareClient:
    """DataClient for SSE/SZSE/BSE/STAR/ChiNext A-shares."""

    def __init__(
        self,
        *,
        timeout: float = 10.0,
        max_news_per_call: int = 50,
    ):
        self.timeout = timeout
        self.max_news = max_news_per_call
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
        })

    def close(self) -> None:
        self._session.close()

    # -----------------------------------------------------------------
    # Protocol methods - skeletons. Real impls in subsequent tasks.
    # -----------------------------------------------------------------

    def get_prices(self, ticker, start_date, end_date, **kwargs) -> list[Price]:
        if not is_ashare(ticker):
            return []
        try:
            from v2.data.ashare.mootdx_prices import fetch_daily_ohlcv
            return fetch_daily_ohlcv(normalize(ticker), start_date, end_date)
        except Exception as e:
            logger.warning("get_prices(%s) failed: %s", ticker, e)
            return []

    def get_financial_metrics(
        self, ticker, end_date, period="ttm", limit=10,
    ) -> list[FinancialMetrics]:
        if not is_ashare(ticker):
            return []
        try:
            from v2.data.ashare.eastmoney_fundamentals import fetch_financial_metrics
            return fetch_financial_metrics(
                normalize(ticker), end_date, period=period, limit=limit,
                session=self._session, timeout=self.timeout,
            )
        except Exception as e:
            logger.warning("get_financial_metrics(%s) failed: %s", ticker, e)
            return []

    def get_news(
        self, ticker, end_date, start_date=None, limit=1000,
    ) -> list[CompanyNews]:
        if not is_ashare(ticker):
            return []
        try:
            from v2.data.ashare.cls_news import fetch_stock_news
            return fetch_stock_news(
                normalize(ticker), end_date,
                start_date=start_date, limit=min(limit, self.max_news),
                session=self._session, timeout=self.timeout,
            )
        except Exception as e:
            logger.warning("get_news(%s) failed: %s", ticker, e)
            return []

    def get_company_facts(self, ticker) -> CompanyFacts | None:
        if not is_ashare(ticker):
            return None
        try:
            from v2.data.ashare.eastmoney_fundamentals import fetch_company_facts
            return fetch_company_facts(
                normalize(ticker),
                session=self._session, timeout=self.timeout,
            )
        except Exception as e:
            logger.warning("get_company_facts(%s) failed: %s", ticker, e)
            return None

    def get_earnings_history(self, ticker, limit=12) -> list[EarningsRecord]:
        if not is_ashare(ticker):
            return []
        try:
            from v2.data.ashare.eastmoney_earnings import fetch_earnings_history
            return fetch_earnings_history(
                normalize(ticker), limit=limit,
                session=self._session, timeout=self.timeout,
            )
        except Exception as e:
            logger.warning("get_earnings_history(%s) failed: %s", ticker, e)
            return []

    def get_market_cap(self, ticker, end_date) -> float | None:
        if not is_ashare(ticker):
            return None
        try:
            from v2.data.ashare.eastmoney_market_cap import fetch_market_cap
            return fetch_market_cap(
                normalize(ticker), end_date,
                session=self._session, timeout=self.timeout,
            )
        except Exception as e:
            logger.warning("get_market_cap(%s) failed: %s", ticker, e)
            return None

    # Optional protocol methods - v1 returns empty / None (analyst data
    # and earnings calendar are v2 scope per spec).

    def get_insider_trades(self, ticker, end_date, start_date=None, limit=1000):
        return []

    def get_earnings(self, ticker):
        return None

    def get_earnings_calendar(self, *, start_date, end_date):
        return []
