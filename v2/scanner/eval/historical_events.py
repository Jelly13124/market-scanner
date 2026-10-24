"""Phase-2 best-effort historical event / fundamental sourcing.

The scanner-eval replay enriches each ticker's :class:`TickerBundle` with the
historical EVENT + FUNDAMENTAL data the event detectors and fundamental signals
need, so they aren't stuck DATA-LIMITED during the no-lookahead backtest. The
``CachedAsOfClient`` then serves these lists clamped to each replay date.

Sourcing strategy — REUSE existing parsers, never reinvent:
  * Earnings history + analyst upgrades/downgrades come straight from
    :class:`~v2.data.yfinance_client.YFinanceClient` (no API key, years of
    history). These unblock the ``earnings_event`` surprise phase and the
    ``analyst_rating`` detector.
  * Insider history comes from an optional Finnhub-style client (depth-limited
    on the free tier); news from an optional EODHD-style client. Both injected.
  * Fundamentals history is the weak link: no existing client returns a
    *historical* :class:`FinancialMetrics` series (Finnhub gives only a current
    snapshot). :func:`fetch_financials_history` derives what it confidently can
    from yfinance's raw quarterly statements (margins + YoY growth) and leaves
    the rest (valuation multiples, ROE/ROIC) unset — see its docstring.

CONTRACT: every fetcher is best-effort. On ANY failure it returns ``[]`` (or a
zeroed count) and NEVER raises — the caller time-boxes the whole pass via a
``deadline`` and isolates per-ticker errors. ``yfinance`` is lazy-imported
INSIDE the functions that need it so this module imports without it installed.
"""

from __future__ import annotations

import logging
import time
from datetime import date

from src.tools.api import search_line_items
from v2.data.models import FinancialMetrics
from v2.data.yfinance_client import YFinanceClient

logger = logging.getLogger(__name__)

#: Raw statement line items pulled per fiscal period for the fundamental factors.
#: These are the dynamic fields ``v2/self_evolve/factors.py`` reads off each
#: ``LineItem`` (total assets / EPS / book value / revenue + cost / gross profit /
#: net income). yfinance-backed via ``search_line_items`` — annual period only.
_LINE_ITEM_FIELDS = [
    "total_assets",
    "earnings_per_share",
    "book_value_per_share",
    "revenue",
    "cost_of_revenue",
    "gross_profit",
    "net_income",
]


# ---------------------------------------------------------------------------
# Availability probe
# ---------------------------------------------------------------------------


def probe_availability(
    sample_ticker: str = "AAPL",
    *,
    insider_client=None,
    news_client=None,
) -> dict:
    """Quick best-effort liveness check of each source on one ticker.

    Returns a dict of booleans::

        {"earnings": bool, "analyst": bool, "insider": bool,
         "news": bool, "financials": bool}

    Each probe is wrapped in try/except and reports ``False`` on any failure
    (or when the corresponding optional client is ``None``). Used to set
    expectations before a long replay — e.g. to warn that fundamental signals
    will be DATA-LIMITED if ``financials`` comes back ``False``.
    """
    end = time.strftime("%Y-%m-%d")
    start = "1900-01-01"

    def _truthy(fn) -> bool:
        try:
            return bool(fn())
        except Exception as e:  # noqa: BLE001 — best-effort probe
            logger.debug("probe_availability source failed: %s", e)
            return False

    result = {
        "earnings": _truthy(lambda: fetch_earnings_history(sample_ticker, limit=4)),
        "analyst": _truthy(lambda: fetch_analyst_actions(sample_ticker, start_date=start, end_date=end, limit=10)),
        "insider": _truthy(
            lambda: insider_client is not None
            and fetch_insider_window(
                sample_ticker,
                start_date=start,
                end_date=end,
                insider_client=insider_client,
            )
        ),
        "news": _truthy(
            lambda: news_client is not None
            and fetch_news_history(
                sample_ticker,
                start_date=start,
                end_date=end,
                news_client=news_client,
            )
        ),
        "financials": _truthy(lambda: fetch_financials_history(sample_ticker)),
    }
    logger.info("probe_availability(%s) -> %s", sample_ticker, result)
    return result


# ---------------------------------------------------------------------------
# Event fetchers — reuse existing clients, best-effort
# ---------------------------------------------------------------------------


def fetch_earnings_history(ticker: str, *, limit: int = 40) -> list:
    """Historical EPS actual/estimate records via ``YFinanceClient``.

    Best-effort: returns ``[]`` on any failure.
    """
    try:
        return YFinanceClient().get_earnings_history(ticker, limit=limit)
    except Exception as e:  # noqa: BLE001 — best-effort
        logger.debug("fetch_earnings_history(%s) failed: %s", ticker, e)
        return []


def fetch_analyst_actions(
    ticker: str,
    *,
    start_date: str,
    end_date: str,
    limit: int = 200,
) -> list:
    """Historical analyst upgrades/downgrades via ``YFinanceClient``.

    Best-effort: returns ``[]`` on any failure.
    """
    try:
        return YFinanceClient().get_analyst_actions(ticker, end_date=end_date, start_date=start_date, limit=limit)
    except Exception as e:  # noqa: BLE001 — best-effort
        logger.debug("fetch_analyst_actions(%s) failed: %s", ticker, e)
        return []


def fetch_insider_window(
    ticker: str,
    *,
    start_date: str,
    end_date: str,
    insider_client,
) -> list:
    """Insider trades in ``[start_date, end_date]`` via an injected client.

    Returns ``[]`` when ``insider_client`` is ``None`` or on any failure.
    """
    if insider_client is None:
        return []
    try:
        return insider_client.get_insider_trades(ticker, end_date=end_date, start_date=start_date, limit=1000)
    except Exception as e:  # noqa: BLE001 — best-effort
        logger.debug("fetch_insider_window(%s) failed: %s", ticker, e)
        return []


def fetch_news_history(
    ticker: str,
    *,
    start_date: str,
    end_date: str,
    news_client,
) -> list:
    """Company news in ``[start_date, end_date]`` via an injected client.

    Returns ``[]`` when ``news_client`` is ``None`` or on any failure.
    """
    if news_client is None:
        return []
    try:
        return news_client.get_news(ticker, end_date=end_date, start_date=start_date, limit=1000)
    except Exception as e:  # noqa: BLE001 — best-effort
        logger.debug("fetch_news_history(%s) failed: %s", ticker, e)
        return []


# ---------------------------------------------------------------------------
# Fundamentals history — intentionally PARTIAL
# ---------------------------------------------------------------------------

# Candidate line-item labels in yfinance's quarterly_financials index. yfinance
# relabels these on Yahoo HTML refreshes, so we match case-insensitively across
# a few known aliases and skip anything we can't find.
_REVENUE_LABELS = ("Total Revenue", "Revenue", "Operating Revenue")
_GROSS_LABELS = ("Gross Profit",)
_OPINC_LABELS = ("Operating Income", "Operating Income Or Loss")
_NETINC_LABELS = (
    "Net Income",
    "Net Income Common Stockholders",
    "Net Income From Continuing Operation Net Minority Interest",
)


def _col_iso(col) -> str | None:
    """Best-effort ``YYYY-MM-DD`` for a statement column header (a Timestamp)."""
    try:
        if hasattr(col, "date"):
            return col.date().isoformat()
        from datetime import datetime as _dt

        return _dt.strptime(str(col)[:10], "%Y-%m-%d").date().isoformat()
    except Exception:  # noqa: BLE001
        return None


def _prior_year_period(period: str, candidates) -> str | None:
    """Return the candidate period date closest to ``period`` minus one year.

    Matches the prior-year quarter by DATE (within a +/- 45-day window of the
    365-day-earlier target) rather than a fixed column offset, so a gap in the
    statement series can't pair the wrong quarters. Returns ``None`` if no
    candidate falls inside the window.
    """
    from datetime import date as _d

    try:
        cur = _d.fromisoformat(period)
    except ValueError:
        return None
    try:
        target = cur.replace(year=cur.year - 1)
    except ValueError:  # Feb 29 → use Feb 28 of prior year.
        target = cur.replace(year=cur.year - 1, day=28)

    best: str | None = None
    best_gap = 46  # strictly inside a 45-day window
    for c in candidates:
        if c == period:
            continue
        try:
            cd = _d.fromisoformat(c)
        except ValueError:
            continue
        gap = abs((cd - target).days)
        if gap <= 45 and gap < best_gap:
            best, best_gap = c, gap
    return best


def _lookup(series, labels) -> float | None:
    """Read the first matching label from a statement column Series.

    Matches case-insensitively. Returns ``None`` if absent / non-finite.
    """
    if series is None:
        return None
    # Fast path: exact label via .get.
    getter = getattr(series, "get", None)
    if getter is not None:
        for lab in labels:
            v = getter(lab)
            f = _finite(v)
            if f is not None:
                return f
    # Case-insensitive fallback over the index, if exposed.
    try:
        idx = list(getattr(series, "index", []))
    except Exception:  # noqa: BLE001
        idx = []
    if idx and getter is not None:
        ci = {str(k).casefold(): k for k in idx}
        for lab in labels:
            key = ci.get(lab.casefold())
            if key is not None:
                f = _finite(getter(key))
                if f is not None:
                    return f
    return None


def _finite(v) -> float | None:
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


def _ratio(num: float | None, den: float | None) -> float | None:
    """``num / den`` guarded against None / non-positive / zero denominators."""
    if num is None or den is None or den <= 0:
        return None
    return num / den


def _growth(curr: float | None, prior: float | None) -> float | None:
    """YoY-style growth ``curr/prior - 1`` guarded; needs positive prior base."""
    if curr is None or prior is None or prior <= 0:
        return None
    return curr / prior - 1.0


def fetch_financials_history(ticker: str) -> list:
    """Best-effort historical :class:`FinancialMetrics` from yfinance statements.

    INTENTIONALLY PARTIAL. We pull yfinance's quarterly income statement
    (``quarterly_financials``) and derive only the fields we can compute
    *confidently* from raw line items:

      * margins — ``gross_margin``, ``operating_margin``, ``net_margin``
        (line item / revenue), and
      * YoY growth — ``revenue_growth``, ``earnings_growth`` (net income proxy),
        ``earnings_per_share_growth`` (net-income proxy; true diluted-share
        adjustment is omitted), computed against the same fiscal quarter one
        year earlier (4 columns back) when that column exists.

    We deliberately do NOT populate valuation multiples (P/E, P/B, P/S, FCF
    yield) or capital-efficiency ratios (ROE/ROIC): those need point-in-time
    price / market-cap / invested-capital that these statements don't carry, and
    a wrong guess silently corrupts the ``value``/``quality`` signals. Periods
    where we can't even compute revenue/margins are skipped. As a result the
    ``value`` signal stays DATA-LIMITED, ``quality`` gets only its margin legs,
    and ``earnings_quality`` gets revenue/earnings/eps growth.

    Returns ``[]`` on ANY exception (including yfinance not installed). The
    ``report_period`` of each emitted metric is the statement column date and
    ``period`` is ``"quarterly"``.

    Known coverage limit (observed live): yfinance's free quarterly statement
    returns only ~5 consecutive quarters, so only the most recent quarter has a
    same-quarter-prior-year column to compare against — the older quarters get
    margins but ``*_growth`` stays ``None``. ``earnings_quality`` will therefore
    be DATA-LIMITED on most historical replay dates.
    """
    try:
        import yfinance as yf

        tk = yf.Ticker(ticker)
        fin = getattr(tk, "quarterly_financials", None)
    except Exception as e:  # noqa: BLE001 — best-effort, yfinance optional
        logger.debug("fetch_financials_history(%s) yfinance failed: %s", ticker, e)
        return []

    if fin is None or getattr(fin, "empty", True):
        return []

    try:
        cols = list(getattr(fin, "columns", []))
    except Exception:  # noqa: BLE001
        return []
    if not cols:
        return []

    # Pre-read each column's revenue/net-income, keyed by ISO period date.
    # YoY growth compares against the column ~365d earlier (matched by DATE, not
    # a fixed i+4 offset, so a missing quarter doesn't silently pair the wrong
    # periods). yfinance orders columns newest-first.
    revenue_by_period: dict[str, float | None] = {}
    netinc_by_period: dict[str, float | None] = {}
    rows: list[tuple[str, object, float | None, float | None]] = []
    for col in cols:
        period = _col_iso(col)
        if period is None:
            continue
        try:
            series = fin[col]
        except Exception:  # noqa: BLE001
            series = None
        rev = _lookup(series, _REVENUE_LABELS)
        ni = _lookup(series, _NETINC_LABELS)
        revenue_by_period[period] = rev
        netinc_by_period[period] = ni
        rows.append((period, series, rev, ni))

    out: list[FinancialMetrics] = []
    for period, series, revenue, netinc in rows:
        gross = _lookup(series, _GROSS_LABELS)
        opinc = _lookup(series, _OPINC_LABELS)

        # Need at least revenue to anchor any margin; otherwise this period
        # carries nothing we trust — skip it.
        if revenue is None or revenue <= 0:
            continue

        prior_period = _prior_year_period(period, revenue_by_period.keys())
        prior_rev = revenue_by_period.get(prior_period) if prior_period else None
        prior_ni = netinc_by_period.get(prior_period) if prior_period else None

        try:
            metric = FinancialMetrics(
                ticker=ticker,
                report_period=period,
                period="quarterly",
                gross_margin=_ratio(gross, revenue),
                operating_margin=_ratio(opinc, revenue),
                net_margin=_ratio(netinc, revenue),
                revenue_growth=_growth(revenue, prior_rev),
                earnings_growth=_growth(netinc, prior_ni),
                # No reliable diluted-share series here → use net income as an
                # EPS proxy for growth direction only.
                earnings_per_share_growth=_growth(netinc, prior_ni),
            )
        except Exception as e:  # noqa: BLE001
            logger.debug(
                "fetch_financials_history(%s) period %s skipped: %s",
                ticker,
                period,
                e,
            )
            continue
        out.append(metric)

    return out


def fetch_line_items_history(ticker: str, *, end_date: str | None = None, limit: int = 10) -> list:
    """Best-effort raw statement line items per fiscal period via ``search_line_items``.

    Pulls the :data:`_LINE_ITEM_FIELDS` (annual period) ending on/before
    ``end_date`` (defaulting to today). Each returned record is a ``LineItem``
    carrying ``report_period`` plus the requested fields as dynamic attributes —
    exactly what the fundamental factors read off it.

    Best-effort like every fetcher here: returns ``[]`` on ANY failure (including
    yfinance not installed inside ``search_line_items``) and NEVER raises.
    """
    end = end_date or date.today().isoformat()
    try:
        recs = search_line_items(ticker, list(_LINE_ITEM_FIELDS), end, period="annual", limit=limit)
    except Exception as e:  # noqa: BLE001 — best-effort
        logger.debug("fetch_line_items_history(%s) failed: %s", ticker, e)
        return []
    return list(recs or [])


# ---------------------------------------------------------------------------
# Bundle enrichment — budget-aware
# ---------------------------------------------------------------------------


def _expired(deadline: float | None) -> bool:
    """True once the monotonic ``deadline`` has passed (None ⇒ never)."""
    return deadline is not None and time.monotonic() >= deadline


def enrich_bundle(
    bundle,
    *,
    start_date: str,
    end_date: str,
    insider_client=None,
    news_client=None,
    do_financials: bool = True,
    deadline: float | None = None,
) -> dict:
    """Populate a :class:`TickerBundle`'s historical lists, best-effort.

    Fills ``earnings_history``, ``analyst_actions``, ``insider``, ``news`` and
    (when ``do_financials``) ``metrics_history`` + ``line_items_history``. Each
    step is guarded and respects ``deadline`` — a ``time.monotonic()`` value past
    which we stop early and leave the remaining lists untouched. Always returns a
    counts dict::

        {"earnings": n, "analyst": n, "insider": n, "news": n,
         "financials": n, "line_items": n}

    Steps already done before the deadline keep their counts; skipped steps
    report ``0``. Never raises.
    """
    counts = {
        "earnings": 0,
        "analyst": 0,
        "insider": 0,
        "news": 0,
        "financials": 0,
        "line_items": 0,
    }

    if not _expired(deadline):
        recs = fetch_earnings_history(bundle.ticker)
        bundle.earnings_history = recs
        counts["earnings"] = len(recs)

    if not _expired(deadline):
        acts = fetch_analyst_actions(bundle.ticker, start_date=start_date, end_date=end_date)
        bundle.analyst_actions = acts
        counts["analyst"] = len(acts)

    if not _expired(deadline):
        ins = fetch_insider_window(
            bundle.ticker,
            start_date=start_date,
            end_date=end_date,
            insider_client=insider_client,
        )
        bundle.insider = ins
        counts["insider"] = len(ins)

    if not _expired(deadline):
        nws = fetch_news_history(
            bundle.ticker,
            start_date=start_date,
            end_date=end_date,
            news_client=news_client,
        )
        bundle.news = nws
        counts["news"] = len(nws)

    if do_financials and not _expired(deadline):
        fins = fetch_financials_history(bundle.ticker)
        bundle.metrics_history = fins
        counts["financials"] = len(fins)

    if do_financials and not _expired(deadline):
        items = fetch_line_items_history(bundle.ticker, end_date=end_date)
        bundle.line_items_history = items
        counts["line_items"] = len(items)

    return counts
