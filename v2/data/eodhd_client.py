"""EODHD adapter implementing the v2 ``DataClient`` Protocol.

EODHD's tiered pricing means a single key may not cover all endpoints. On the
basic EOD plan we have:

    /eod/{ticker}              ✅ daily OHLCV
    /news?s={ticker}           ✅ articles with full text (no per-article sentiment)
    /sentiments?s={ticker}     ✅ per-day aggregate sentiment in [-1, +1]

The rest (`/insider-transactions`, `/calendar/earnings`, `/fundamentals/...`)
return 403 on lower tiers. This client gracefully returns ``[]`` / ``None``
for those — the caller should compose this with another provider that DOES
cover insider/earnings (see ``CompositeClient`` for the hybrid pattern).

Sentiment integration trick:
    ``get_news`` calls **both** ``/news`` and ``/sentiments``, then stamps the
    *daily* aggregate sentiment label onto every article published that day.
    The downstream ``NewsSentimentShiftDetector`` aggregates anyway, so this
    introduces no real loss versus FD's native per-article labels.

Auth: ``EODHD_API_KEY`` env var; sent as ``api_token=`` query param.
Ticker format: appends ``.US`` if no exchange suffix is provided.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

import requests

from v2.data.models import (
    CompanyFacts,
    CompanyNews,
    Earnings,
    EarningsCalendarEntry,
    EarningsRecord,
    FinancialMetrics,
    InsiderTrade,
    Price,
)

logger = logging.getLogger(__name__)


def _classify_sentiment(score: float | None) -> str | None:
    """Map a continuous ``normalized`` score in [-1, +1] to a categorical label
    matching FD's ``CompanyNews.sentiment`` convention.
    """
    if score is None:
        return None
    if score > 0.20:
        return "positive"
    if score < -0.20:
        return "negative"
    return "neutral"


class EODHDClient:
    """EODHD data adapter conforming to ``v2.data.protocol.DataClient``.

    One ``requests.Session`` per instance — not thread-safe to share. Use one
    per worker thread (the scanner runner does this automatically).

    Methods backing endpoints not on your subscription tier return empty/None
    rather than raising. The 403 path is logged at debug level once per call.
    """

    BASE_URL = "https://eodhd.com/api"
    _RETRY_DELAYS = (5, 15, 30)

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("EODHD_API_KEY", "")
        self._timeout = timeout
        self._session = requests.Session()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> EODHDClient:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def close(self) -> None:
        self._session.close()

    # ------------------------------------------------------------------
    # Protocol methods — endpoints we have access to
    # ------------------------------------------------------------------

    def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        **kwargs,
    ) -> list[Price]:
        path = f"/eod/{self._fmt_ticker(ticker)}"
        data = self._get(
            path,
            {
                "from": start_date,
                "to": end_date,
                "order": "a",
                "period": "d",
            },
        )
        if not isinstance(data, list):
            return []
        out: list[Price] = []
        for row in data:
            try:
                adj = row.get("adjusted_close")
                out.append(
                    Price(
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=int(row["volume"]),
                        time=row["date"],
                        adjusted_close=float(adj) if adj is not None else None,
                    )
                )
            except (KeyError, TypeError, ValueError) as e:
                logger.debug("Skipping malformed EOD row for %s: %s", ticker, e)
        return out

    def get_news(
        self,
        ticker: str,
        end_date: str,
        start_date: str | None = None,
        limit: int = 1000,
    ) -> list[CompanyNews]:
        symbol = self._fmt_ticker(ticker)
        # EODHD /news caps server-side at 1000 per call; we pass through.
        params: dict[str, Any] = {"s": symbol, "to": end_date, "limit": min(limit, 1000)}
        if start_date is not None:
            params["from"] = start_date
        articles_raw = self._get("/news", params)
        if not isinstance(articles_raw, list):
            articles_raw = []

        # Daily-aggregate sentiment is the source-of-truth polarity signal —
        # the per-article classification was a lossy bucketing. Carry the
        # continuous score on each article via ``sentiment_score`` and keep
        # the label only for display.
        daily_scores = self._fetch_daily_sentiment(symbol, start_date, end_date)

        out: list[CompanyNews] = []
        days_with_articles: set[str] = set()
        for art in articles_raw:
            try:
                ts = art.get("date", "")
                date_only = ts[:10] if isinstance(ts, str) else None
                if date_only:
                    days_with_articles.add(date_only)
                score = daily_scores.get(date_only) if date_only else None
                label = _classify_sentiment(score)
                url = art.get("link") or art.get("url")
                # EODHD news rows don't always have a 'source'; derive from URL host.
                source = art.get("source") or _host_from_url(url) or "EODHD"
                out.append(
                    CompanyNews(
                        ticker=ticker,
                        title=art.get("title", "") or "",
                        source=source,
                        date=date_only,
                        url=url,
                        sentiment=label,
                        sentiment_score=score,
                    )
                )
            except Exception as e:
                logger.debug("Skipping malformed news row for %s: %s", ticker, e)

        # Synthesize one "aggregate" CompanyNews per day in the requested
        # window that the /news call didn't cover. Popular tickers blow past
        # /news's 1000-article cap inside a week, leaving the 90-day baseline
        # window empty — without these synthetic rows, NewsSentimentShiftDetector
        # sees "0 baseline articles" and silently no-ops. The daily-aggregate
        # score is the signal we actually care about, articles are scaffolding.
        for day, score in daily_scores.items():
            if day in days_with_articles:
                continue
            out.append(
                CompanyNews(
                    ticker=ticker,
                    title="(daily sentiment aggregate)",
                    source="EODHD",
                    date=day,
                    sentiment=_classify_sentiment(score),
                    sentiment_score=score,
                )
            )
        return out

    # ------------------------------------------------------------------
    # Protocol methods — endpoints NOT included in the basic tier
    # ------------------------------------------------------------------

    def get_financial_metrics(
        self,
        ticker: str,
        end_date: str,
        period: str = "ttm",
        limit: int = 10,
    ) -> list[FinancialMetrics]:
        # /fundamentals/{ticker} is 403 on the basic plan. Compose with another
        # provider (Finnhub, yfinance) if you need ratio data on EODHD-basic.
        return []

    def get_insider_trades(
        self,
        ticker: str,
        end_date: str,
        start_date: str | None = None,
        limit: int = 1000,
    ) -> list[InsiderTrade]:
        # /insider-transactions is 403 on the basic plan.
        return []

    def get_company_facts(self, ticker: str) -> CompanyFacts | None:
        # /fundamentals/{ticker} (company metadata is bundled here) is 403 on basic.
        return None

    def get_earnings(self, ticker: str) -> Earnings | None:
        # /calendar/earnings is 403 on the basic plan.
        return None

    def get_earnings_history(
        self,
        ticker: str,
        limit: int = 12,
    ) -> list[EarningsRecord]:
        # See get_earnings — same 403 path.
        return []

    def get_earnings_calendar(
        self,
        *,
        start_date: str,
        end_date: str,
    ) -> list[EarningsCalendarEntry]:
        # /calendar/earnings is 403 on the basic plan; no forward calendar feed.
        return []

    def get_market_cap(self, ticker: str, end_date: str) -> float | None:
        # Lives inside /fundamentals on EODHD — 403 on basic.
        return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fmt_ticker(self, ticker: str) -> str:
        """Append ``.US`` if no exchange suffix is present (EODHD convention)."""
        ticker = ticker.strip().upper()
        return ticker if "." in ticker else f"{ticker}.US"

    def _fetch_daily_sentiment(
        self,
        symbol: str,
        start_date: str | None,
        end_date: str,
    ) -> dict[str, float]:
        """Hit /sentiments and return {date: normalized_score}. Empty on failure."""
        params: dict[str, Any] = {"s": symbol, "to": end_date}
        if start_date is not None:
            params["from"] = start_date
        payload = self._get("/sentiments", params)
        if not isinstance(payload, dict):
            return {}
        rows = payload.get(symbol) or []
        if not isinstance(rows, list):
            return {}
        out: dict[str, float] = {}
        for r in rows:
            try:
                d = r.get("date")
                s = r.get("normalized")
                if d and s is not None:
                    out[d] = float(s)
            except (TypeError, ValueError):
                continue
        return out

    def _get(self, path: str, params: dict) -> Any:
        """GET path with retry on 429. Returns parsed JSON or None."""
        url = self.BASE_URL + path
        merged = {**params, "api_token": self._api_key, "fmt": "json"}
        for attempt, delay in enumerate((*self._RETRY_DELAYS, None)):
            try:
                resp = self._session.get(url, params=merged, timeout=self._timeout)
            except requests.RequestException as exc:
                logger.warning("EODHD request error on %s: %s", path, exc)
                return None
            if resp.status_code == 429 and delay is not None:
                logger.info(
                    "EODHD 429 on %s, retrying in %ds (attempt %d/%d)",
                    path,
                    delay,
                    attempt + 1,
                    len(self._RETRY_DELAYS),
                )
                time.sleep(delay)
                continue
            if resp.status_code == 403:
                logger.debug("EODHD %s 403 (endpoint not on this subscription tier)", path)
                return None
            if resp.status_code >= 400:
                logger.warning(
                    "EODHD %s returned %d: %s",
                    path,
                    resp.status_code,
                    resp.text[:200],
                )
                return None
            try:
                return resp.json()
            except ValueError:
                logger.warning("EODHD %s returned non-JSON body", path)
                return None
        logger.warning("EODHD rate-limit exhausted on %s", path)
        return None


def _host_from_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        # cheap host extraction without urllib import overhead
        after_scheme = url.split("://", 1)[-1]
        host = after_scheme.split("/", 1)[0]
        # strip "www."
        if host.startswith("www."):
            host = host[4:]
        return host or None
    except Exception:
        return None
