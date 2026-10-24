"""yfinance adapter — partial ``DataClient`` for analyst + earnings data.

yfinance scrapes Yahoo Finance's unofficial endpoints. It's the most pragmatic
free source we have for analyst coverage AND for the trailing earnings-history
that Finnhub's free tier strips down to a single quarter. Methods we don't
cover raise ``NotImplementedError`` so misuse fails loud.

``CompositeClient`` routes ``get_analyst_*`` and ``get_earnings_history`` here;
everything else goes to EODHD/Finnhub.
"""

from __future__ import annotations

import logging
from datetime import date as _date, datetime as _datetime
from typing import Any

from v2.data.models import (
    AnalystAction,
    AnalystTarget,
    CompanyFacts,
    CompanyNews,
    Earnings,
    EarningsData,
    EarningsRecord,
    EstimateRevisions,
    FinancialMetrics,
    InsiderTrade,
    Price,
)

logger = logging.getLogger(__name__)


_ACTION_MAP = {
    "up": "up",
    "upgrade": "up",
    "down": "down",
    "downgrade": "down",
    "main": "main",
    "maintain": "main",
    "reiterated": "reit",
    "reit": "reit",
    "init": "init",
    "initiated": "init",
    "initiation": "init",
}


def _normalize_action(raw: Any) -> str:
    """Map a yfinance Action column value to our 5-bucket vocabulary."""
    if raw is None:
        return "main"
    s = str(raw).strip().lower()
    return _ACTION_MAP.get(s, "main")


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        import math
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _label_eps_surprise_yf(actual: float | None, estimate: float | None) -> str | None:
    """Categorize EPS surprise (BEAT/MISS/MEET) — mirrors Finnhub's tolerance."""
    if actual is None or estimate is None:
        return None
    tol = max(abs(estimate) * 0.01, 0.01)
    if actual > estimate + tol:
        return "BEAT"
    if actual < estimate - tol:
        return "MISS"
    return "MEET"


def _safe_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        import math
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return int(f)
    except (TypeError, ValueError):
        return None


class YFinanceClient:
    """Partial ``DataClient`` — implements analyst data only.

    Threading: each worker thread should hold its own instance. ``yfinance.Ticker``
    creates a new requests session per call internally, so the client itself
    carries no shared state, but keeping instances per-worker matches the
    pattern enforced by every other backend.
    """

    def __init__(self, *, request_timeout: float = 5.0) -> None:
        self._timeout = request_timeout

    def __enter__(self) -> "YFinanceClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        """No-op — yfinance has no explicit session to release."""
        pass

    # ------------------------------------------------------------------
    # AnalystDataClient methods — the only ones we actually implement
    # ------------------------------------------------------------------

    def get_analyst_targets(
        self,
        ticker: str,
        *,
        asof_date: str | None = None,
    ) -> AnalystTarget | None:
        """Snapshot of analyst price targets. ``asof_date`` is informational
        only — yfinance returns current consensus regardless."""
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            raw = t.analyst_price_targets
        except Exception as e:
            logger.warning("yfinance analyst_price_targets failed for %s: %s", ticker, e)
            return None

        if not isinstance(raw, dict) or not raw:
            return None

        when = asof_date or _date.today().isoformat()
        try:
            return AnalystTarget(
                ticker=ticker,
                current_price=_safe_float(raw.get("current")),
                target_mean=_safe_float(raw.get("mean")),
                target_median=_safe_float(raw.get("median")),
                target_high=_safe_float(raw.get("high")),
                target_low=_safe_float(raw.get("low")),
                n_analysts=_safe_int(raw.get("numberOfAnalysts") or raw.get("number_of_analysts")),
                asof_date=when,
            )
        except Exception as e:
            logger.debug("Malformed analyst target row for %s: %s", ticker, e)
            return None

    def get_analyst_actions(
        self,
        ticker: str,
        *,
        end_date: str,
        start_date: str,
        limit: int = 100,
    ) -> list[AnalystAction]:
        """List of upgrade / downgrade / initiation events in [start, end].

        Sorted newest-first; capped at ``limit``.
        """
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            df = t.upgrades_downgrades
        except Exception as e:
            logger.warning("yfinance upgrades_downgrades failed for %s: %s", ticker, e)
            return []

        if df is None or getattr(df, "empty", True):
            return []

        try:
            start = _datetime.strptime(start_date[:10], "%Y-%m-%d").date()
            end = _datetime.strptime(end_date[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return []

        out: list[AnalystAction] = []
        # The DataFrame's index is GradeDate (datetime). Iterating gives
        # (timestamp, row) tuples.
        for ts, row in df.iterrows():
            try:
                if hasattr(ts, "date"):
                    d = ts.date()
                elif isinstance(ts, _date):
                    d = ts
                else:
                    d = _datetime.strptime(str(ts)[:10], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue
            if d < start or d > end:
                continue
            try:
                action_raw = row.get("Action") if hasattr(row, "get") else row["Action"]
                firm = row.get("Firm") if hasattr(row, "get") else row["Firm"]
                from_g = row.get("FromGrade") if hasattr(row, "get") else row["FromGrade"]
                to_g = row.get("ToGrade") if hasattr(row, "get") else row["ToGrade"]
            except (KeyError, AttributeError) as e:
                logger.debug("Malformed action row for %s: %s", ticker, e)
                continue
            out.append(AnalystAction(
                ticker=ticker,
                action_date=d.isoformat(),
                firm=str(firm) if firm is not None else "",
                from_grade=str(from_g) if from_g else None,
                to_grade=str(to_g) if to_g else None,
                action=_normalize_action(action_raw),
            ))
        # yfinance returns newest-first already, but be defensive.
        out.sort(key=lambda a: a.action_date, reverse=True)
        return out[:limit]

    def get_estimate_revisions(
        self,
        ticker: str,
        *,
        period: str = "0q",
        asof_date: str | None = None,
    ) -> EstimateRevisions | None:
        """Net up/down EPS estimate revisions for one period.

        ``period`` selects which row of yfinance's ``eps_revisions`` DataFrame
        to read — ``"0q"`` (current quarter, default), ``"+1q"`` (next quarter),
        ``"0y"`` / ``"+1y"`` (current/next fiscal year). Returns ``None`` when
        yfinance has no coverage for the ticker (common for small caps) so the
        detector can exclude the ticker from its stats — this is the same
        ``None vs triggered=False`` distinction enforced elsewhere.
        """
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            df = t.eps_revisions
        except Exception as e:
            logger.warning("yfinance eps_revisions failed for %s: %s", ticker, e)
            return None

        if df is None or getattr(df, "empty", True):
            return None

        # Period rows are indexed by the period string. yfinance occasionally
        # uses a "period" column instead of an index — handle both shapes.
        try:
            if hasattr(df, "loc") and period in getattr(df, "index", []):
                row = df.loc[period]
            elif "period" in getattr(df, "columns", []):
                match = df[df["period"] == period]
                if match.empty:
                    return None
                row = match.iloc[0]
            else:
                # Index doesn't include this period — sparse coverage.
                return None
        except Exception as e:
            logger.debug("eps_revisions row lookup failed for %s/%s: %s", ticker, period, e)
            return None

        def _safe_count(value: Any) -> int:
            n = _safe_int(value)
            return n if n is not None else 0

        # yfinance is inconsistent about column casing — observed live:
        # ``upLast7days`` (lowercase d) but ``downLast7Days`` (uppercase D),
        # and they could flip again on any Yahoo HTML refresh. Look up by
        # case-folded name so either casing works. NB: pandas Index can't be
        # bool-evaluated; use list() to materialize before iterating.
        try:
            keys = list(getattr(row, "index", []))
            ci_lookup = {str(k).casefold(): row.get(k) for k in keys}
        except Exception:
            ci_lookup = {}

        def _by_keys(*candidates: str) -> Any:
            for k in candidates:
                v = ci_lookup.get(k.casefold())
                if v is not None:
                    return v
            return None

        when = asof_date or _date.today().isoformat()
        try:
            return EstimateRevisions(
                ticker=ticker,
                asof_date=when,
                period=period,
                up_last_7d=_safe_count(_by_keys("upLast7days", "upLast7Days")),
                down_last_7d=_safe_count(_by_keys("downLast7Days", "downLast7days")),
                up_last_30d=_safe_count(_by_keys("upLast30days", "upLast30Days")),
                down_last_30d=_safe_count(_by_keys("downLast30Days", "downLast30days")),
            )
        except Exception as e:
            logger.debug("Malformed eps_revisions row for %s/%s: %s", ticker, period, e)
            return None

    # ------------------------------------------------------------------
    # Everything else — explicit raise so misuse fails loud
    # ------------------------------------------------------------------

    def _refuse(self, name: str) -> "NotImplementedError":
        return NotImplementedError(
            f"YFinanceClient.{name}() is not implemented — this is a partial "
            f"adapter for analyst data only. Route {name!r} to another "
            f"backend via CompositeClient."
        )

    def get_prices(self, *args: Any, **kwargs: Any) -> list[Price]:
        raise self._refuse("get_prices")

    def get_financial_metrics(self, *args: Any, **kwargs: Any) -> list[FinancialMetrics]:
        raise self._refuse("get_financial_metrics")

    def get_news(self, *args: Any, **kwargs: Any) -> list[CompanyNews]:
        raise self._refuse("get_news")

    def get_insider_trades(self, *args: Any, **kwargs: Any) -> list[InsiderTrade]:
        raise self._refuse("get_insider_trades")

    def get_company_facts(self, *args: Any, **kwargs: Any) -> CompanyFacts | None:
        raise self._refuse("get_company_facts")

    def get_earnings(self, *args: Any, **kwargs: Any) -> Earnings | None:
        raise self._refuse("get_earnings")

    def get_earnings_history(
        self,
        ticker: str,
        limit: int = 12,
    ) -> list[EarningsRecord]:
        # Yahoo's get_earnings_dates returns BOTH past actuals and future
        # scheduled announcements in one frame; drop the future rows (no
        # Reported EPS) so the EarningsSurpriseDetector only sees real history.
        # Finnhub's free tier strips this down to one quarter, so this method
        # is what unblocks both live z-scoring and historical backtesting.
        import yfinance as yf
        try:
            df = yf.Ticker(ticker).get_earnings_dates(limit=int(limit) * 2)
        except Exception as e:
            logger.debug("yfinance get_earnings_dates failed for %s: %s", ticker, e)
            return []
        if df is None or df.empty:
            return []

        out: list[EarningsRecord] = []
        for ts, row in df.iterrows():
            actual = _safe_float(row.get("Reported EPS"))
            if actual is None:
                # Future scheduled row — drop.
                continue
            estimate = _safe_float(row.get("EPS Estimate"))
            try:
                announce_date = ts.date().isoformat()
            except Exception:
                continue
            quarterly = EarningsData(
                earnings_per_share=actual,
                estimated_earnings_per_share=estimate,
                eps_surprise=_label_eps_surprise_yf(actual, estimate),
            )
            out.append(EarningsRecord(
                ticker=ticker,
                report_period=announce_date,
                source_type="yfinance",
                filing_date=announce_date,
                quarterly=quarterly,
            ))

        out.sort(key=lambda r: r.filing_date or "", reverse=True)
        return out[: int(limit)]

    def get_market_cap(self, *args: Any, **kwargs: Any) -> float | None:
        raise self._refuse("get_market_cap")
