"""Data provider protocol — the interface all data sources implement.

Any class with these methods can be used as a data provider throughout
the v2 pipeline. No inheritance required — Python's structural typing
handles the rest.

Example::

    class YFinanceClient:
        def get_prices(self, ticker, start_date, end_date, **kwargs):
            # fetch from yfinance, return list[Price]
            ...

    # Works anywhere the pipeline expects a DataClient
    client: DataClient = YFinanceClient()
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

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
)


@runtime_checkable
class DataClient(Protocol):
    """Protocol that all data providers must satisfy.

    Methods return empty lists or None on failure — never raise.
    """

    def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        **kwargs,
    ) -> list[Price]: ...

    def get_financial_metrics(
        self,
        ticker: str,
        end_date: str,
        period: str = "ttm",
        limit: int = 10,
    ) -> list[FinancialMetrics]: ...

    def get_news(
        self,
        ticker: str,
        end_date: str,
        start_date: str | None = None,
        limit: int = 1000,
    ) -> list[CompanyNews]: ...

    def get_insider_trades(
        self,
        ticker: str,
        end_date: str,
        start_date: str | None = None,
        limit: int = 1000,
    ) -> list[InsiderTrade]: ...

    def get_company_facts(self, ticker: str) -> CompanyFacts | None: ...

    def get_earnings(self, ticker: str) -> Earnings | None: ...

    def get_earnings_history(
        self,
        ticker: str,
        limit: int = 12,
    ) -> list[EarningsRecord]: ...

    def get_earnings_calendar(
        self,
        *,
        start_date: str,
        end_date: str,
    ) -> list[EarningsCalendarEntry]:
        """Scheduled earnings events in [start_date, end_date] (ISO YYYY-MM-DD).

        Returns the universe-wide calendar — caller filters to its tickers.
        Bulk-fetched once per scan rather than per-ticker. Backends that
        don't expose a calendar feed should return an empty list (caller
        falls back to "no upcoming earnings info available").
        """
        ...

    def get_market_cap(self, ticker: str, end_date: str) -> float | None: ...


@runtime_checkable
class AnalystDataClient(DataClient, Protocol):
    """Optional sub-protocol for providers that supply analyst data.

    Kept distinct from the base ``DataClient`` so most providers (FD, Finnhub,
    EODHD) don't need to stub these methods — only a yfinance-style backend
    that actually has analyst coverage needs to implement them. Callers should
    ``isinstance(client, AnalystDataClient)`` check before invoking.
    """

    def get_analyst_targets(
        self,
        ticker: str,
        *,
        asof_date: str | None = None,
    ) -> AnalystTarget | None: ...

    def get_analyst_actions(
        self,
        ticker: str,
        *,
        end_date: str,
        start_date: str,
        limit: int = 100,
    ) -> list[AnalystAction]: ...

    def get_estimate_revisions(
        self,
        ticker: str,
        *,
        period: str = "0q",
        asof_date: str | None = None,
    ) -> EstimateRevisions | None: ...
