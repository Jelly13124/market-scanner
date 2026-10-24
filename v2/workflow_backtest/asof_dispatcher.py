from __future__ import annotations

from v2.scanner.eval.cached_asof_client import CachedAsOfClient, TickerBundle


class AsOfDispatcher:
    """Multi-ticker as-of client. Wraps one CachedAsOfClient per ticker bundle and
    routes get_*(ticker, ...) calls to it after applying the shared as-of ceiling.
    Implements the DataClient surface the agents + scanner call. Unknown tickers
    return the empty/None default (never raise)."""

    def __init__(self, bundles: dict[str, TickerBundle]) -> None:
        self._clients = {t: CachedAsOfClient(b) for t, b in bundles.items()}
        self._asof: str | None = None

    def set_asof(self, date_iso: str) -> None:
        self._asof = date_iso[:10]
        for c in self._clients.values():
            c.set_asof(self._asof)

    def _c(self, ticker: str):
        return self._clients.get(ticker)

    def get_prices(self, ticker, start_date, end_date, **kw):
        c = self._c(ticker)
        return c.get_prices(ticker, start_date, end_date, **kw) if c else []

    def get_financial_metrics(self, ticker, end_date, period="ttm", limit=10):
        c = self._c(ticker)
        return c.get_financial_metrics(ticker, end_date, period, limit) if c else []

    def get_news(self, ticker, end_date, start_date=None, limit=1000):
        c = self._c(ticker)
        return c.get_news(ticker, end_date, start_date, limit) if c else []

    def get_insider_trades(self, ticker, end_date, start_date=None, limit=1000):
        c = self._c(ticker)
        return c.get_insider_trades(ticker, end_date, start_date, limit) if c else []

    def get_company_facts(self, ticker):
        c = self._c(ticker)
        return c.get_company_facts(ticker) if c else None

    def get_market_cap(self, ticker, end_date):
        c = self._c(ticker)
        return c.get_market_cap(ticker, end_date) if c else None

    def get_earnings_history(self, ticker, limit=12):
        c = self._c(ticker)
        return c.get_earnings_history(ticker, limit) if c else []

    def get_earnings(self, ticker):
        c = self._c(ticker)
        return c.get_earnings(ticker) if c else None

    def get_earnings_calendar(self, *, start_date, end_date):
        return []

    def get_analyst_actions(self, ticker, *, end_date, start_date, limit=100):
        c = self._c(ticker)
        return (
            c.get_analyst_actions(ticker, end_date=end_date, start_date=start_date, limit=limit)
            if c
            else []
        )

    def get_analyst_targets(self, ticker, *, asof_date=None):
        c = self._c(ticker)
        return c.get_analyst_targets(ticker, asof_date=asof_date) if c else None

    def get_estimate_revisions(self, ticker, *, period="0q", asof_date=None):
        c = self._c(ticker)
        return c.get_estimate_revisions(ticker, period=period, asof_date=asof_date) if c else None

    def close(self) -> None:
        pass
