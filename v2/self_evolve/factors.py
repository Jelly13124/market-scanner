"""No-lookahead factor computation — the load-bearing kernel of the self-evolve loop.

Factors are computed AS-OF each rebalance date with a hard no-lookahead ceiling.
This mirrors the discipline of ``v2/scanner/eval/cached_asof_client.py``:

* **Prices** use only bars dated ``<= asof``. A future bar (even one that exists in
  the bundle) can never enter a factor — every series is clamped before any math.
* **Fundamentals** use only records whose ``report_period`` is ``<= asof - 60d``.
  A statement covering period ``D`` is not knowable on day ``D``; it is filed weeks
  later, modelled by the fixed :data:`FUNDAMENTAL_AVAILABILITY_LAG_DAYS` (60 days).
  At ceiling ``asof`` we may therefore only read periods ``D <= asof - 60d``.

The public entry point is :func:`compute_factors`. It is **total and defensive**:
a ticker with insufficient price history is OMITTED entirely (never crashes), and
missing fundamentals yield ``None`` for ``value`` / ``quality`` while the price
factors still compute. It never raises on bad/sparse data.

Bundles are duck-typed — each value exposes ``.prices`` (objects with ``.time`` /
``.close``) and ``.metrics_history`` (objects with ``.report_period`` /
``.earnings_per_share`` / ``.return_on_equity`` / ``.price_to_earnings_ratio``).
All access is via :func:`getattr` so plain ``SimpleNamespace`` fakes work in tests.

Pure Python — no network, no pandas, no LLM.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta

#: A statement for fiscal period ``D`` is only knowable at ``D + 60d``. Equivalently,
#: at as-of ceiling ``C`` we may only read fundamentals with ``report_period <= C - 60d``.
#: Matches ``cached_asof_client.FUNDAMENTAL_AVAILABILITY_LAG_DAYS`` — the same lag the
#: backtest replay client enforces.
FUNDAMENTAL_AVAILABILITY_LAG_DAYS = 60

#: The classic 12-1 momentum skip: drop the most recent ~21 trading days (≈1 month)
#: so short-term reversal does not contaminate the medium-term momentum signal.
MOMENTUM_SKIP_DAYS = 21

#: Minimum number of as-of bars required to compute price factors. A ticker with
#: fewer is OMITTED. Two clean returns are the floor for a meaningful stdev; in
#: practice the lookback windows demand far more, but this guards the degenerate case.
MIN_PRICE_BARS = 2

#: The factor keys this module produces, in canonical order. Mirrors
#: ``config.FACTOR_KEYS`` — kept local to avoid a hard import dependency.
FACTOR_KEYS = ("momentum", "low_vol", "reversal", "value", "quality")


# ---------------------------------------------------------------------------
# Date helpers (local; defensive — never raise). Mirror cached_asof_client.
# ---------------------------------------------------------------------------


def _parse_iso(s: str | None) -> str | None:
    """Return the ``YYYY-MM-DD`` prefix of an ISO date, or ``None`` if unparseable.

    Defensive: missing / malformed input yields ``None`` so callers treat the row
    as not-available (excluded) rather than crashing.
    """
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date().isoformat()
    except (ValueError, TypeError):
        return None


def _minus_days(iso: str, n: int) -> str:
    """Parse ``YYYY-MM-DD``, subtract ``n`` calendar days, reformat to ``YYYY-MM-DD``."""
    d = datetime.strptime(iso[:10], "%Y-%m-%d").date() - timedelta(days=n)
    return d.isoformat()


# ---------------------------------------------------------------------------
# As-of price series extraction + offset lookup
# ---------------------------------------------------------------------------


def _asof_closes(prices: list, asof: str) -> list[tuple[str, float]]:
    """Extract ``(date, close)`` pairs dated ``<= asof``, ascending by date.

    The HARD no-lookahead clamp: any bar dated after ``asof`` is dropped here, so no
    downstream factor can ever observe a future price. Bars with an unparseable date
    or a non-numeric close are skipped (treated as not-available).
    """
    out: list[tuple[str, float]] = []
    for p in prices:
        d = _parse_iso(getattr(p, "time", None))
        if d is None or d > asof:
            continue
        close = getattr(p, "close", None)
        if not isinstance(close, (int, float)) or isinstance(close, bool):
            continue
        out.append((d, float(close)))
    out.sort(key=lambda dc: dc[0])
    return out


def _close_at_or_before(series: list[tuple[str, float]], target: str) -> float | None:
    """Close of the bar NEAREST to ``target`` at-or-before it, or ``None`` if none.

    ``series`` must be ascending by date (as :func:`_asof_closes` returns). Walks
    from the newest end and returns the first close dated ``<= target``. ``None``
    means every bar is strictly after ``target`` (not enough history that far back).
    """
    for d, close in reversed(series):
        if d <= target:
            return close
    return None


# ---------------------------------------------------------------------------
# Lagged fundamentals (60-day availability lag)
# ---------------------------------------------------------------------------


def _latest_lagged_metric(metrics_history: list, asof: str):
    """Newest metrics record with ``report_period <= asof - 60d``, or ``None``.

    Enforces the fundamental availability lag: a record whose period falls inside
    the 60-day window before ``asof`` is NOT yet knowable and is excluded. Among the
    knowable records the one with the latest ``report_period`` wins. Records with an
    unparseable ``report_period`` are skipped.
    """
    cutoff = _minus_days(asof, FUNDAMENTAL_AVAILABILITY_LAG_DAYS)
    best = None
    best_d: str | None = None
    for m in metrics_history:
        d = _parse_iso(getattr(m, "report_period", None))
        if d is None or d > cutoff:
            continue
        if best_d is None or d > best_d:
            best, best_d = m, d
    return best


# ---------------------------------------------------------------------------
# Per-ticker factor computation
# ---------------------------------------------------------------------------


def _compute_one(bundle, asof: str, config) -> dict[str, float] | None:
    """Factors for a single ticker, or ``None`` if price history is insufficient.

    Price factors (momentum / low_vol / reversal) require enough as-of bars; when
    any cannot be computed from the available history the ticker is OMITTED (return
    ``None``) rather than emitting a partial/garbage row. Fundamental factors
    (value / quality) degrade to ``None`` independently — a missing statement does
    not drop the ticker.
    """
    prices = getattr(bundle, "prices", None) or []
    series = _asof_closes(prices, asof)
    if len(series) < MIN_PRICE_BARS:
        return None

    lookback = getattr(config, "lookback", {})
    momentum_days = int(lookback["momentum_days"])
    vol_days = int(lookback["vol_days"])
    reversal_days = int(lookback["reversal_days"])

    asof_close = series[-1][1]

    # -- momentum: classic 12-1. close[asof - 21d] / close[asof - momentum_days] - 1.
    # Both endpoints snap to the nearest bar at-or-before their target offset date.
    recent_target = _minus_days(asof, MOMENTUM_SKIP_DAYS)
    far_target = _minus_days(asof, momentum_days)
    recent_close = _close_at_or_before(series, recent_target)
    far_close = _close_at_or_before(series, far_target)
    if recent_close is None or far_close is None or far_close == 0.0:
        return None
    momentum = recent_close / far_close - 1.0

    # -- reversal: negative of the short-window return. Recent up → reversal < 0.
    rev_target = _minus_days(asof, reversal_days)
    rev_close = _close_at_or_before(series, rev_target)
    if rev_close is None or rev_close == 0.0:
        return None
    reversal = -(asof_close / rev_close - 1.0)

    # -- low_vol: negative of the stdev of daily returns over the trailing vol_days
    # as-of BARS (bar count, not calendar days). Needs >= 2 returns → 3 bars.
    window = series[-(vol_days + 1) :] if vol_days > 0 else []
    rets: list[float] = []
    for i in range(1, len(window)):
        prev = window[i - 1][1]
        if prev == 0.0:
            continue
        rets.append(window[i][1] / prev - 1.0)
    if len(rets) < 2:
        return None
    low_vol = -statistics.pstdev(rets)

    # -- value / quality: from the latest fundamentals record at <= asof - 60d.
    value = _value_from_metric(_latest_lagged_metric(getattr(bundle, "metrics_history", None) or [], asof))
    quality = _quality_from_metric(_latest_lagged_metric(getattr(bundle, "metrics_history", None) or [], asof))

    return {
        "momentum": momentum,
        "low_vol": low_vol,
        "reversal": reversal,
        "value": value,
        "quality": quality,
    }


def _value_from_metric(metric) -> float | None:
    """Earnings yield = ``1 / price_to_earnings_ratio`` when ``pe > 0``, else ``None``.

    A non-positive or missing P/E is not a meaningful earnings yield, so it maps to
    ``None`` (the ticker keeps its price factors; ``value`` is just absent).
    """
    if metric is None:
        return None
    pe = getattr(metric, "price_to_earnings_ratio", None)
    if not isinstance(pe, (int, float)) or isinstance(pe, bool):
        return None
    if pe <= 0.0:
        return None
    return 1.0 / pe


def _quality_from_metric(metric) -> float | None:
    """Return-on-equity off the lagged record, or ``None`` if absent / non-numeric."""
    if metric is None:
        return None
    roe = getattr(metric, "return_on_equity", None)
    if not isinstance(roe, (int, float)) or isinstance(roe, bool):
        return None
    return float(roe)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def compute_factors(bundles, asof: str, config) -> dict[str, dict[str, float]]:
    """Compute as-of factors for every ticker with sufficient history.

    Parameters
    ----------
    bundles
        ``{ticker: bundle}`` where each bundle exposes ``.prices`` and
        ``.metrics_history`` (duck-typed; see module docstring).
    asof
        The rebalance date (``YYYY-MM-DD...``). A HARD ceiling: prices dated after
        it and fundamentals with ``report_period > asof - 60d`` are invisible.
    config
        A strategy config exposing ``config.lookback`` with integer
        ``momentum_days`` / ``vol_days`` / ``reversal_days``.

    Returns
    -------
    dict
        ``{ticker: {"momentum", "low_vol", "reversal", "value", "quality"}}``. A
        ticker with insufficient price history is OMITTED. ``value`` / ``quality``
        may be ``None`` when no lagged fundamentals are available. Never raises.
    """
    asof_iso = _parse_iso(asof)
    out: dict[str, dict[str, float]] = {}
    if asof_iso is None:
        return out
    for ticker, bundle in bundles.items():
        factors = _compute_one(bundle, asof_iso, config)
        if factors is not None:
            out[ticker] = factors
    return out
