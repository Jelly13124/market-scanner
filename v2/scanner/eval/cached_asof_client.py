"""CachedAsOfClient — a no-lookahead replay data client for the backtest harness.

The keystone of the scanner backtest. We replay ``detector.detect(ticker, asof, fd)``
over historical days; ``fd`` must serve ONLY data that existed as-of the replay
date. If a detector accidentally peeks at a future bar / filing / news item, every
downstream verdict is contaminated by lookahead bias and the whole evaluation is
worthless.

Design: fetch all of a ticker's history ONCE into a :class:`TickerBundle`, then
wrap it in a :class:`CachedAsOfClient` that implements the full
:class:`~v2.data.protocol.DataClient` (and analyst sub-protocol) surface. Every
accessor clamps to records dated ``<= asof`` — a HARD ceiling that holds
*regardless* of the ``start_date`` / ``end_date`` the caller passes. A detector
that mis-computes its own ``end`` can never see the future.

As-of clamp rule per accessor: keep rows whose date ``d`` satisfies
``d <= min(caller_end, asof)`` (where there is no caller end, just ``<= asof``),
and ``d >= start_date`` when a start bound is supplied.

Fundamental availability lag: a financial statement covering period ``D`` is not
actually *knowable* on day ``D`` — it is filed weeks later. We model this with a
fixed :data:`FUNDAMENTAL_AVAILABILITY_LAG_DAYS` (60d): a metric for period ``D`` is
only served once the ceiling reaches ``D + 60d``.

Defensive contract (mirrors the real backends): accessors NEVER raise. A row with
an unparseable or missing date is treated as not-yet-available and excluded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from v2.data.models import (
    AnalystAction,
    AnalystTarget,
    CompanyFacts,
    CompanyNews,
    EarningsCalendarEntry,
    EarningsRecord,
    Earnings,
    EstimateRevisions,
    FinancialMetrics,
    InsiderTrade,
    Price,
)

#: A statement for fiscal period ``D`` is only "known" (filed/available) at
#: ``D + 60d``. Used solely by :meth:`CachedAsOfClient.get_financial_metrics`.
FUNDAMENTAL_AVAILABILITY_LAG_DAYS = 60


# ---------------------------------------------------------------------------
# Date helpers (local; defensive — never raise)
# ---------------------------------------------------------------------------


def _parse_iso(s: str | None) -> str | None:
    """Return the ``YYYY-MM-DD`` prefix of an ISO date, or ``None`` if unparseable.

    Defensive: missing / malformed input yields ``None`` so callers can treat
    the row as not-yet-available (excluded) rather than crashing the replay.
    """
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date().isoformat()
    except (ValueError, TypeError):
        return None


def _minus_days(iso: str, n: int) -> str:
    """Parse ``YYYY-MM-DD``, subtract ``n`` days, reformat to ``YYYY-MM-DD``."""
    d = datetime.strptime(iso[:10], "%Y-%m-%d").date() - timedelta(days=n)
    return d.isoformat()


# ---------------------------------------------------------------------------
# TickerBundle
# ---------------------------------------------------------------------------


@dataclass
class TickerBundle:
    """All of one ticker's pre-fetched history, fetched once for the backtest.

    Lists hold the full history; :class:`CachedAsOfClient` clamps them to the
    as-of ceiling on every read. ``prices`` is expected time-ascending but the
    client re-sorts defensively where order matters.
    """

    ticker: str
    prices: list = field(default_factory=list)            # list[Price], time-ascending
    earnings_history: list = field(default_factory=list)  # list[EarningsRecord]
    insider: list = field(default_factory=list)           # list[InsiderTrade]
    news: list = field(default_factory=list)              # list[CompanyNews]
    metrics_history: list = field(default_factory=list)   # list[FinancialMetrics]
    analyst_actions: list = field(default_factory=list)   # list[AnalystAction]
    analyst_targets: list = field(default_factory=list)   # list[AnalystTarget]
    facts: object | None = None                           # CompanyFacts | None
    market_cap: float | None = None


# ---------------------------------------------------------------------------
# CachedAsOfClient
# ---------------------------------------------------------------------------


class CachedAsOfClient:
    """Serves a :class:`TickerBundle` through the ``DataClient`` protocol, clamped
    to a hard ``<= asof`` no-lookahead ceiling.

    Call :meth:`set_asof` to position the replay date before any accessor; every
    read then returns only records dated on or before that ceiling.
    """

    def __init__(self, bundle: TickerBundle) -> None:
        self._bundle = bundle
        self._asof: str | None = None

    # -- ceiling control ----------------------------------------------------

    def set_asof(self, date_iso: str) -> None:
        """Set the hard as-of ceiling (``YYYY-MM-DD``). Clamps all subsequent reads."""
        self._asof = date_iso[:10]

    def _ceil(self) -> str:
        if self._asof is None:
            raise RuntimeError("set_asof() must be called before use")
        return self._asof

    def _effective_end(self, caller_end: str | None) -> str:
        """min(caller_end, asof) as a ``YYYY-MM-DD`` string; asof alone if no end."""
        ceil = self._ceil()
        end = _parse_iso(caller_end)
        if end is None:
            return ceil
        return min(end, ceil)

    # -- prices -------------------------------------------------------------

    def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        **kwargs,
    ) -> list[Price]:
        end = self._effective_end(end_date)
        start = _parse_iso(start_date)
        out: list[Price] = []
        for p in self._bundle.prices:
            d = _parse_iso(getattr(p, "time", None))
            if d is None or d > end:
                continue
            if start is not None and d < start:
                continue
            out.append(p)
        out.sort(key=lambda p: _parse_iso(p.time) or "")
        return out

    # -- financial metrics (60-day availability lag) ------------------------

    def get_financial_metrics(
        self,
        ticker: str,
        end_date: str,
        period: str = "ttm",
        limit: int = 10,
    ) -> list[FinancialMetrics]:
        # A statement for period D is only knowable at D + 60d. Equivalently:
        # at ceiling C we may only see periods with D <= C - 60d.
        cutoff = _minus_days(self._effective_end(end_date), FUNDAMENTAL_AVAILABILITY_LAG_DAYS)
        out: list[FinancialMetrics] = []
        for m in self._bundle.metrics_history:
            d = _parse_iso(getattr(m, "report_period", None))
            if d is None or d > cutoff:
                continue
            out.append(m)
        out.sort(key=lambda m: _parse_iso(m.report_period) or "", reverse=True)
        return out[:limit]

    # -- news ---------------------------------------------------------------

    def get_news(
        self,
        ticker: str,
        end_date: str,
        start_date: str | None = None,
        limit: int = 1000,
    ) -> list[CompanyNews]:
        end = self._effective_end(end_date)
        start = _parse_iso(start_date)
        out: list[CompanyNews] = []
        for n in self._bundle.news:
            d = _parse_iso(getattr(n, "date", None))
            if d is None or d > end:
                continue
            if start is not None and d < start:
                continue
            out.append(n)
        out.sort(key=lambda n: _parse_iso(n.date) or "", reverse=True)
        return out[:limit]

    # -- insider trades -----------------------------------------------------

    def get_insider_trades(
        self,
        ticker: str,
        end_date: str,
        start_date: str | None = None,
        limit: int = 1000,
    ) -> list[InsiderTrade]:
        end = self._effective_end(end_date)
        start = _parse_iso(start_date)
        out: list[InsiderTrade] = []
        for r in self._bundle.insider:
            d = self._insider_date(r)
            if d is None or d > end:
                continue
            if start is not None and d < start:
                continue
            out.append(r)
        out.sort(key=self._insider_date, reverse=True)
        return out[:limit]

    @staticmethod
    def _insider_date(r) -> str | None:
        """Effective availability date of an insider row.

        Prefer ``transaction_date`` (when the trade happened); fall back to
        ``filing_date`` (the always-present field). Returns ``None`` if neither
        parses, so the row is excluded.
        """
        return _parse_iso(getattr(r, "transaction_date", None)) or _parse_iso(
            getattr(r, "filing_date", None)
        )

    # -- company facts (static snapshot) ------------------------------------

    def get_company_facts(self, ticker: str) -> CompanyFacts | None:
        return self._bundle.facts

    # -- earnings (snapshot; not historically reconstructed) ----------------

    def get_earnings(self, ticker: str) -> Earnings | None:
        return None

    # -- earnings history ---------------------------------------------------

    def get_earnings_history(
        self,
        ticker: str,
        limit: int = 12,
    ) -> list[EarningsRecord]:
        ceil = self._ceil()
        out: list[EarningsRecord] = []
        for e in self._bundle.earnings_history:
            d = _parse_iso(getattr(e, "filing_date", None))
            if d is None or d > ceil:
                continue
            out.append(e)
        out.sort(key=lambda e: _parse_iso(e.filing_date) or "", reverse=True)
        return out[:limit]

    # -- earnings calendar (upcoming; cannot be backfilled) -----------------

    def get_earnings_calendar(
        self,
        *,
        start_date: str,
        end_date: str,
    ) -> list[EarningsCalendarEntry]:
        # Upcoming earnings dates can't be reconstructed historically without a
        # point-in-time calendar snapshot — documented as empty for the replay.
        return []

    # -- market cap (static snapshot) ---------------------------------------

    def get_market_cap(self, ticker: str, end_date: str) -> float | None:
        return self._bundle.market_cap

    # -- analyst actions ----------------------------------------------------

    def get_analyst_actions(
        self,
        ticker: str,
        *,
        end_date: str,
        start_date: str,
        limit: int = 100,
    ) -> list[AnalystAction]:
        end = self._effective_end(end_date)
        start = _parse_iso(start_date)
        out: list[AnalystAction] = []
        for a in self._bundle.analyst_actions:
            d = _parse_iso(getattr(a, "action_date", None))
            if d is None or d > end:
                continue
            if start is not None and d < start:
                continue
            out.append(a)
        out.sort(key=lambda a: _parse_iso(a.action_date) or "", reverse=True)
        return out[:limit]

    # -- analyst targets ----------------------------------------------------

    def get_analyst_targets(
        self,
        ticker: str,
        *,
        asof_date: str | None = None,
    ) -> AnalystTarget | None:
        # Tighten to the explicit asof_date arg when given, but never beyond the
        # hard ceiling.
        ceil = self._ceil()
        arg = _parse_iso(asof_date)
        bound = min(arg, ceil) if arg is not None else ceil
        best: AnalystTarget | None = None
        best_d: str | None = None
        for t in self._bundle.analyst_targets:
            d = _parse_iso(getattr(t, "asof_date", None))
            if d is None or d > bound:
                continue
            if best_d is None or d > best_d:
                best, best_d = t, d
        return best

    # -- estimate revisions (snapshot; not reconstructed) -------------------

    def get_estimate_revisions(
        self,
        ticker: str,
        *,
        period: str = "0q",
        asof_date: str | None = None,
    ) -> EstimateRevisions | None:
        return None

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        # No pooled connection to release — cached client holds plain data.
        return None
