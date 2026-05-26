"""Finnhub adapter implementing the v2 ``DataClient`` Protocol.

Finnhub's free tier offers 60 calls/min and 5000 calls/day across all
endpoints. This client enforces a global token bucket (60 tokens, refilled
at ~1/sec) AND a per-instance throttle so a misbehaving thread cannot burst
the rate ceiling on its own. Run with ``recommend_max_workers("finnhub")``
(currently 4) when scanning a large universe.

Auth: ``FINNHUB_API_KEY`` env var (or pass ``api_key=`` to the constructor).
Header sent as ``X-Finnhub-Token``.

Endpoint mappings (free tier):
    get_prices              -> /stock/candle (daily candles)
    get_financial_metrics   -> /stock/metric (single snapshot, not a time series)
    get_news                -> /company-news (no per-article sentiment — see note)
    get_insider_trades      -> /stock/insider-transactions
    get_company_facts       -> /stock/profile2
    get_earnings            -> /stock/earnings (latest)
    get_earnings_history    -> /stock/earnings (last N)
    get_market_cap          -> /stock/profile2 (latest market cap in millions, converted)

News sentiment note:
    Finnhub's free tier does **not** expose per-article sentiment. All
    ``CompanyNews.sentiment`` fields are ``None``; downstream sentiment-
    based detectors degrade cleanly to "no triggered events" rather than
    inventing fake polarity scores. The aggregate ``/news-sentiment``
    endpoint exists but isn't on the DataClient Protocol — see
    ``v2/scanner/detectors/news_sentiment.py`` for the rationale.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

import requests

from v2.data.models import (
    CompanyFacts,
    CompanyNews,
    Earnings,
    EarningsCalendarEntry,
    EarningsData,
    EarningsRecord,
    FinancialMetrics,
    InsiderTrade,
    Price,
    Quote,
)

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Global rate limiter — shared across all FinnhubClient instances in this process.
# -----------------------------------------------------------------------------

class _TokenBucket:
    """Refills *capacity* tokens at *refill_rate* per second."""

    def __init__(self, capacity: float, refill_rate: float) -> None:
        self._capacity = float(capacity)
        self._tokens = float(capacity)
        self._refill_rate = float(refill_rate)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last
                self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate)
                self._last = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True
                deficit = tokens - self._tokens
                wait = deficit / self._refill_rate
            if deadline is not None and time.monotonic() + wait > deadline:
                return False
            time.sleep(min(wait, 0.5))


# Finnhub free tier: 60 req/min. ``capacity=1`` is intentional — a higher
# burst (we previously had 60) lets 4 workers each grab a token instantly,
# fire 60+ requests inside a second, and saturate Finnhub's 60-second
# rolling window. Subsequent requests then 429 for ~60s while our 3-attempt
# retry (5/15/30s) burns through and gives up returning empty data — the
# detector silently sees "no insider trades" and nothing fires. With
# ``capacity=1`` and a 5%-margin refill, calls are strictly serialized
# globally at ~57/min across all workers.
_global_bucket = _TokenBucket(capacity=1.0, refill_rate=0.95)


# -----------------------------------------------------------------------------
# Transaction-code mapping for /stock/insider-transactions
# -----------------------------------------------------------------------------

# SEC Form 4 transaction codes — only open-market trades reflect informed
# conviction. Derivative conversions (M), grants (A), tax-withholding sales
# (F), and dispositions to issuers (D) are non-discretionary and routinely
# generate noise. We previously counted them as buys/sells which inflated
# insider clusters with option exercises that don't carry signal.
#
# Codes left out below (M / A / F / D / G / X / etc.) map to ``transaction_shares=0``
# and won't move the cluster needle.
_BUY_CODES = {"P"}    # P: Open-market purchase — the only un-ambiguous insider bet.
_SELL_CODES = {"S"}   # S: Open-market sale — same logic on the other side.


class FinnhubClient:
    """Finnhub data adapter conforming to ``v2.data.protocol.DataClient``.

    NOT thread-safe internally (one ``requests.Session`` per instance).
    Use one client per worker thread; ``run_scan`` already does this via its
    per-worker pool.
    """

    BASE_URL = "https://finnhub.io/api/v1"
    _RETRY_DELAYS = (5, 15, 30)

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 30.0,
        min_call_interval: float = 1.05,
    ) -> None:
        self._api_key = api_key or os.environ.get("FINNHUB_API_KEY", "")
        self._timeout = timeout
        self._session = requests.Session()
        if self._api_key:
            self._session.headers["X-Finnhub-Token"] = self._api_key
        self._min_interval = min_call_interval
        self._last_call_at = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Context manager (parity with FDClient)
    # ------------------------------------------------------------------

    def __enter__(self) -> FinnhubClient:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def close(self) -> None:
        self._session.close()

    # ------------------------------------------------------------------
    # Protocol methods
    # ------------------------------------------------------------------

    def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        **kwargs,
    ) -> list[Price]:
        start_ts = _date_to_unix(start_date)
        end_ts = _date_to_unix(end_date, end_of_day=True)
        data = self._get("/stock/candle", {
            "symbol": ticker,
            "resolution": "D",
            "from": start_ts,
            "to": end_ts,
        })
        if not data or data.get("s") != "ok":
            return []
        out: list[Price] = []
        try:
            opens = data["o"]
            highs = data["h"]
            lows = data["l"]
            closes = data["c"]
            vols = data["v"]
            times = data["t"]
            n = min(len(opens), len(highs), len(lows), len(closes), len(vols), len(times))
            for i in range(n):
                out.append(Price(
                    open=float(opens[i]),
                    high=float(highs[i]),
                    low=float(lows[i]),
                    close=float(closes[i]),
                    volume=int(vols[i]),
                    time=datetime.fromtimestamp(times[i], tz=timezone.utc).date().isoformat(),
                ))
        except (KeyError, TypeError, ValueError) as e:
            logger.warning("Malformed /stock/candle response for %s: %s", ticker, e)
            return []
        return out

    def get_financial_metrics(
        self,
        ticker: str,
        end_date: str,
        period: str = "ttm",
        limit: int = 10,
    ) -> list[FinancialMetrics]:
        data = self._get("/stock/metric", {"symbol": ticker, "metric": "all"})
        if not data or not isinstance(data, dict):
            return []
        m = data.get("metric") or {}
        if not m:
            return []
        # Finnhub returns a snapshot, not a panel — synthesize one row.
        mapped = FinancialMetrics(
            ticker=ticker,
            report_period=end_date,
            period=period,
            currency=None,
            market_cap=_safe_float(m.get("marketCapitalization"), scale=1_000_000.0),
            price_to_earnings_ratio=_safe_float(m.get("peTTM")),
            price_to_book_ratio=_safe_float(m.get("pbAnnual")),
            price_to_sales_ratio=_safe_float(m.get("psTTM")),
            # Finnhub returns these as percentage-form numbers (45 = 45%);
            # v1 agents universally expect decimal form (0.45 = 45%) — every
            # threshold check is `> 0.15` etc. and `f"{v:.2%}"` formats decimal.
            # Without scale=0.01 every "profitability" check fires (45 > 0.15)
            # and ROE renders as "4500%".
            return_on_equity=_safe_float(m.get("roeTTM"), scale=0.01),
            return_on_assets=_safe_float(m.get("roaTTM"), scale=0.01),
            gross_margin=_safe_float(m.get("grossMarginTTM"), scale=0.01),
            operating_margin=_safe_float(m.get("operatingMarginTTM"), scale=0.01),
            net_margin=_safe_float(m.get("netProfitMarginTTM"), scale=0.01),
            current_ratio=_safe_float(m.get("currentRatioAnnual")),
            quick_ratio=_safe_float(m.get("quickRatioAnnual")),
            debt_to_equity=_safe_float(m.get("totalDebt/totalEquityAnnual")),
            revenue_growth=_safe_float(m.get("revenueGrowthTTMYoy"), scale=0.01),
            earnings_per_share_growth=_safe_float(m.get("epsGrowthTTMYoy"), scale=0.01),
            earnings_per_share=_safe_float(m.get("epsTTM")),
            book_value_per_share=_safe_float(m.get("bookValuePerShareAnnual")),
        )
        return [mapped]

    def get_news(
        self,
        ticker: str,
        end_date: str,
        start_date: str | None = None,
        limit: int = 1000,
    ) -> list[CompanyNews]:
        if start_date is None:
            # Default: trailing 30 days.
            end_dt = datetime.fromisoformat(end_date)
            start_dt = datetime.fromtimestamp(end_dt.timestamp() - 30 * 86400, tz=timezone.utc)
            start_date = start_dt.date().isoformat()
        data = self._get("/company-news", {
            "symbol": ticker,
            "from": start_date,
            "to": end_date,
        })
        if not isinstance(data, list):
            return []
        out: list[CompanyNews] = []
        for row in data[:limit]:
            try:
                ts = row.get("datetime")
                d = (
                    datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat()
                    if ts is not None else None
                )
                out.append(CompanyNews(
                    ticker=ticker,
                    title=row.get("headline", "") or "",
                    source=row.get("source", "") or "",
                    date=d,
                    url=row.get("url"),
                    sentiment=None,  # not available on free tier
                ))
            except Exception as e:
                logger.debug("Skipping malformed news row for %s: %s", ticker, e)
        return out

    def get_insider_trades(
        self,
        ticker: str,
        end_date: str,
        start_date: str | None = None,
        limit: int = 1000,
    ) -> list[InsiderTrade]:
        params: dict[str, Any] = {"symbol": ticker, "to": end_date}
        if start_date is not None:
            params["from"] = start_date
        data = self._get("/stock/insider-transactions", params)
        if not isinstance(data, dict):
            return []
        rows = data.get("data") or []
        out: list[InsiderTrade] = []
        for row in rows[:limit]:
            try:
                code = (row.get("transactionCode") or "").strip().upper()
                shares = _safe_float(row.get("change"), default=0.0) or 0.0
                price = _safe_float(row.get("transactionPrice"), default=0.0) or 0.0
                # Sign shares by transaction code so downstream (transaction_value
                # > 0 = buy) works uniformly with FDClient.
                if code in _BUY_CODES:
                    signed_shares = abs(shares)
                elif code in _SELL_CODES:
                    signed_shares = -abs(shares)
                else:
                    signed_shares = 0.0
                value = signed_shares * price
                out.append(InsiderTrade(
                    ticker=ticker,
                    name=row.get("name") or "",
                    filing_date=row.get("filingDate") or row.get("transactionDate") or "",
                    transaction_date=row.get("transactionDate"),
                    transaction_type=code or None,
                    transaction_shares=signed_shares,
                    transaction_price_per_share=price if price > 0 else None,
                    transaction_value=value if signed_shares else None,
                    is_board_director=False,  # not provided
                ))
            except Exception as e:
                logger.debug("Skipping malformed insider row for %s: %s", ticker, e)
        return out

    def get_company_facts(self, ticker: str) -> CompanyFacts | None:
        data = self._get("/stock/profile2", {"symbol": ticker})
        if not data or not isinstance(data, dict):
            return None
        if not data.get("ticker") and not data.get("name"):
            return None
        return CompanyFacts(
            ticker=ticker,
            is_active=True,
            name=data.get("name"),
            industry=data.get("finnhubIndustry"),
            sector=data.get("finnhubIndustry"),  # Finnhub doesn't split GICS sector
            exchange=data.get("exchange"),
            location=data.get("country"),
            market_cap=_safe_float(data.get("marketCapitalization"), scale=1_000_000.0),
        )

    def get_earnings(self, ticker: str) -> Earnings | None:
        records = self.get_earnings_history(ticker, limit=1)
        if not records:
            return None
        r = records[0]
        return Earnings(
            ticker=ticker,
            report_period=r.report_period,
            fiscal_period=r.fiscal_period,
            currency=r.currency,
            quarterly=r.quarterly,
            annual=r.annual,
        )

    def get_earnings_history(
        self,
        ticker: str,
        limit: int = 12,
    ) -> list[EarningsRecord]:
        # Use /calendar/earnings (not /stock/earnings) — the calendar endpoint
        # returns the REAL announcement date (the "date" field) plus actual/
        # estimate EPS + revenue. /stock/earnings has no filing date at all
        # and forced us to use the fiscal period end as a stand-in, which made
        # every record look 30+ business days stale to EarningsSurpriseDetector.
        #
        # The calendar requires a [from, to] range. We fetch a wide trailing
        # window (~limit * 100 days, capped at 4 years) so we get N quarters
        # back. Finnhub returns at most one row per ticker per quarter so over-
        # fetching is cheap.
        from datetime import date as _date, timedelta as _td
        today = _date.today()
        span_days = min(int(limit) * 100, 365 * 4)
        params = {
            "from": (today - _td(days=span_days)).isoformat(),
            "to": today.isoformat(),
            "symbol": ticker,
        }
        payload = self._get("/calendar/earnings", params)
        if not isinstance(payload, dict):
            return []
        rows = payload.get("earningsCalendar") or []
        if not isinstance(rows, list):
            return []

        out: list[EarningsRecord] = []
        for row in rows:
            try:
                actual = _safe_float(row.get("epsActual"))
                estimate = _safe_float(row.get("epsEstimate"))
                surprise_label = _label_eps_surprise(actual, estimate)
                rev_actual = _safe_float(row.get("revenueActual"))
                rev_estimate = _safe_float(row.get("revenueEstimate"))
                quarterly = EarningsData(
                    earnings_per_share=actual,
                    estimated_earnings_per_share=estimate,
                    eps_surprise=surprise_label,
                    revenue=rev_actual,
                    estimated_revenue=rev_estimate,
                    revenue_surprise=_label_eps_surprise(rev_actual, rev_estimate),
                )
                # `date` is the real announcement date. `hour` ("bmo"/"amc"/"dmh")
                # is which side of the trading day — we don't currently use it.
                announce_date = row.get("date")
                out.append(EarningsRecord(
                    ticker=ticker,
                    report_period=announce_date or "",
                    source_type="finnhub",
                    filing_date=announce_date,
                    fiscal_period=_quarter_label(row.get("quarter"), row.get("year")),
                    quarterly=quarterly,
                ))
            except Exception as e:
                logger.debug("Skipping malformed earnings row for %s: %s", ticker, e)
        # Sort newest-first to mirror /stock/earnings behavior; cap at `limit`.
        out.sort(key=lambda r: r.filing_date or "", reverse=True)
        return out[: int(limit)]

    def get_earnings_calendar(
        self,
        *,
        start_date: str,
        end_date: str,
    ) -> list[EarningsCalendarEntry]:
        """Forward-looking earnings calendar between [start_date, end_date].

        Unlike ``get_earnings_history`` (which restricts to one symbol and
        looks BACKWARD), this is a universe-wide BULK fetch — one call
        returns every scheduled earnings event for every covered symbol in
        the window. The runner uses this once per scan to mark tickers
        with imminent catalysts.
        """
        payload = self._get("/calendar/earnings", {"from": start_date, "to": end_date})
        if not isinstance(payload, dict):
            return []
        rows = payload.get("earningsCalendar") or []
        if not isinstance(rows, list):
            return []

        out: list[EarningsCalendarEntry] = []
        for row in rows:
            try:
                symbol = (row.get("symbol") or "").strip().upper()
                event_date = row.get("date")
                if not symbol or not event_date:
                    continue
                year_f = _safe_float(row.get("year"))
                quarter_f = _safe_float(row.get("quarter"))
                out.append(EarningsCalendarEntry(
                    symbol=symbol,
                    date=event_date,
                    hour=row.get("hour") or None,
                    eps_estimate=_safe_float(row.get("epsEstimate")),
                    revenue_estimate=_safe_float(row.get("revenueEstimate")),
                    year=int(year_f) if year_f is not None else None,
                    quarter=int(quarter_f) if quarter_f is not None else None,
                ))
            except Exception as e:
                logger.debug("Skipping malformed calendar row: %s", e)
        return out

    def get_market_cap(self, ticker: str, end_date: str) -> float | None:
        # WARNING: end_date is ignored — Finnhub /stock/profile2 returns current
        # market cap only. Acceptable for live scans; wrong for historical backfills.
        facts = self.get_company_facts(ticker)
        return facts.market_cap if facts else None

    def get_quote(self, ticker: str) -> Quote | None:
        """Live(-ish) intraday quote — current + open/high/low + today's % move.

        Returns None for tickers Finnhub doesn't price (unknown symbol gives
        all-zero payload). Used by the watchlist UI to surface "where is this
        stock right now" next to scan-time scores.
        """
        data = self._get("/quote", {"symbol": ticker})
        if not isinstance(data, dict):
            return None
        c = data.get("c")
        # Finnhub returns {c:0, h:0, l:0, ...} for unknown symbols. Treat as
        # missing data — anything with current=0 is suspect anyway.
        if c is None or c == 0:
            return None
        return Quote(
            ticker=ticker,
            current_price=_safe_float(c),
            prev_close=_safe_float(data.get("pc")),
            percent_change=_safe_float(data.get("dp")),
            asof_timestamp=int(data["t"]) if isinstance(data.get("t"), (int, float)) and data.get("t") else None,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, params: dict) -> Any:
        """GET path with rate-limiting + 429 retry. Returns parsed JSON or None."""
        self._throttle()
        url = self.BASE_URL + path
        for attempt, delay in enumerate((*self._RETRY_DELAYS, None)):
            _global_bucket.acquire(1.0)
            try:
                resp = self._session.get(url, params=params, timeout=self._timeout)
            except requests.RequestException as exc:
                logger.warning("Request error on %s: %s", path, exc)
                return None
            if resp.status_code == 429 and delay is not None:
                logger.info(
                    "Finnhub 429, retrying in %ds (attempt %d/%d)",
                    delay, attempt + 1, len(self._RETRY_DELAYS),
                )
                time.sleep(delay)
                continue
            if resp.status_code == 403:
                # Free tier blocks some endpoints (e.g., /stock/candle moved to
                # premium). Log once at debug level to avoid log flood — the
                # detector handles the None return cleanly.
                logger.debug("Finnhub %s 403 (premium endpoint or quota)", path)
                return None
            if resp.status_code >= 400:
                logger.warning("Finnhub %s returned %d", path, resp.status_code)
                return None
            try:
                return resp.json()
            except ValueError:
                logger.warning("Finnhub %s returned non-JSON body", path)
                return None
        logger.warning("Finnhub rate-limit exhausted on %s", path)
        return None

    def _throttle(self) -> None:
        """Enforce min_call_interval per-instance (defensive, beyond the global bucket)."""
        with self._lock:
            now = time.monotonic()
            gap = now - self._last_call_at
            if gap < self._min_interval:
                time.sleep(self._min_interval - gap)
            self._last_call_at = time.monotonic()


# -----------------------------------------------------------------------------
# Utility functions
# -----------------------------------------------------------------------------


def _date_to_unix(date_str: str, *, end_of_day: bool = False) -> int:
    """YYYY-MM-DD -> unix timestamp (UTC, start or end of day)."""
    dt = datetime.fromisoformat(date_str[:10]).replace(tzinfo=timezone.utc)
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return int(dt.timestamp())


def _safe_float(
    v: Any,
    default: float | None = None,
    *,
    scale: float = 1.0,
) -> float | None:
    """Best-effort float conversion. Returns *default* on None / nan / error."""
    if v is None:
        return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f or f == float("inf") or f == -float("inf"):  # NaN or inf
        return default
    return f * scale


def _label_eps_surprise(actual: float | None, estimate: float | None) -> str | None:
    """Categorize EPS surprise the same way FD does: BEAT / MISS / MEET."""
    if actual is None or estimate is None:
        return None
    # 1% tolerance — anything within this is "meet".
    tol = max(abs(estimate) * 0.01, 0.01)
    if actual > estimate + tol:
        return "BEAT"
    if actual < estimate - tol:
        return "MISS"
    return "MEET"


def _quarter_label(quarter: Any, year: Any) -> str | None:
    """'Q3 2024' style label from Finnhub's separate quarter+year fields."""
    if quarter is None or year is None:
        return None
    try:
        return f"Q{int(quarter)} {int(year)}"
    except (TypeError, ValueError):
        return None
