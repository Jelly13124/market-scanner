"""Per-sample factor backtest — the fitness function of the self-evolve loop.

:func:`backtest` is how a candidate :class:`~v2.self_evolve.config.StrategyConfig`
is SCORED on one fixed sample window (``train`` / ``val`` / ``test``). It is a
deliberately coarse, monthly, fully-invested long-only simulation built directly
on the two pieces the loop already owns:

* :func:`v2.self_evolve.samples.rebalance_dates` — the deterministic monthly
  rebalance calendar within the sample's fixed window, and
* :func:`v2.self_evolve.strategy_gen.generate_holdings` — the ``{ticker: weight}``
  book the config produces as-of each rebalance date.

Mechanics (each step degrades gracefully — the function never raises):

1. **Calendar.** ``trading_days`` = the sorted UNION of every bundle's price
   dates. ``dates`` = the monthly rebalance days inside ``SAMPLES[sample]``.
2. **Hold-to-next.** Each rebalance date ``d`` is entered with ``w =
   generate_holdings(bundles, d, config)`` and held until the NEXT rebalance date
   ``d'``. The period return is ``Σ_t w_t * (close_t[d'] / close_t[d] - 1)`` using
   each ticker's own as-of / forward closes; a ticker missing a price at *either*
   endpoint contributes 0 to that period (it simply earns nothing, never a crash).
   The LAST rebalance date has no forward window, so it is the final exit point —
   with ``N`` rebalance dates there are ``N-1`` held periods.
3. **Equity curve.** Start at :data:`START_CAPITAL`, compound the per-period
   returns, and stamp each point with a real :class:`datetime.datetime` ``Date``
   (NOT a string) — required so the metrics calculator's drawdown-date
   ``.strftime`` cannot crash on a real drawdown.
4. **Metrics** via :class:`~src.backtesting.metrics.PerformanceMetricsCalculator`
   built with ``annual_trading_days=PERIODS_PER_YEAR`` (12) so its built-in
   ``sqrt`` Sharpe annualization and risk-free scaling match the MONTHLY cadence
   of this curve rather than a daily one.

Conventions (documented, sensible defaults — see the constants below):

* ``ann_return`` — geometric / CAGR: ``(final/initial) ** (12 / n_periods) - 1``.
* ``ann_vol``    — ``pstdev(period_returns) * sqrt(12)`` (annualized monthly stdev).
* ``max_drawdown`` — passed through from the calculator AS-IS. That value is
  ALREADY a percent (the calculator multiplies by 100); we do NOT multiply again.
* ``turnover``   — ONE-WAY: mean over rebalances (that have a prior book) of
  ``0.5 * Σ_t |w_t - w_{t-1}|``. Identical books ⇒ 0; a full rotation ⇒ ~1.0.
* ``n_rebalances`` — ``len(dates)``: the number of monthly rebalance dates found
  in the window. Held periods (and equity-curve returns) number ``n_rebalances - 1``.

With fewer than 2 rebalance dates (no held period) or an empty universe the
function returns the dict with the metric fields ``None`` / ``turnover`` 0 and the
honest ``n_rebalances`` count — never a crash.

Pure Python aside from the pandas/numpy inside the shared metrics calculator —
no network, no LLM.
"""

from __future__ import annotations

import datetime as _dt
import math
import statistics

from src.backtesting.metrics import PerformanceMetricsCalculator
from v2.self_evolve.samples import rebalance_dates
from v2.self_evolve.strategy_gen import generate_holdings

#: Notional starting capital for the compounded equity curve. Pure scale — every
#: reported metric (returns, vol, drawdown, sharpe) is scale-invariant in it.
START_CAPITAL = 100_000.0

#: Rebalance periods per year for the (monthly) cadence. Drives BOTH the
#: annualization of ``ann_return`` / ``ann_vol`` here AND the metrics calculator's
#: ``annual_trading_days`` so its Sharpe / risk-free scaling is monthly, not daily.
PERIODS_PER_YEAR = 12

#: The metric fields, mapped to ``None`` for the too-short / empty short-circuit.
#: ``turnover`` / ``n_rebalances`` are filled with real numbers (0) instead.
_METRIC_KEYS = ("sharpe", "ann_return", "ann_vol", "max_drawdown")


def _close_on(prices, day: str) -> float | None:
    """The close exactly ON ISO date ``day`` (first 10 chars matched), else ``None``.

    The bundle's ``.time`` may carry a time component; we match on the date prefix.
    A missing / non-numeric close returns ``None`` so the caller can treat that
    ticker as contributing nothing over the period rather than crashing.
    """
    for p in prices or []:
        t = getattr(p, "time", None)
        if not isinstance(t, str) or t[:10] != day:
            continue
        close = getattr(p, "close", None)
        if not isinstance(close, (int, float)) or isinstance(close, bool):
            return None
        return float(close)
    return None


def _period_return(bundles, weights: dict[str, float], entry: str, exit_: str) -> float:
    """``Σ_t w_t * (close_t[exit] / close_t[entry] - 1)`` over the held book.

    A ticker missing a price at the entry OR exit date (or with a zero entry close)
    contributes 0 to the period — it earns nothing rather than poisoning the sum
    with a NaN/inf or raising.
    """
    total = 0.0
    for ticker, w in weights.items():
        bundle = bundles.get(ticker)
        if bundle is None:
            continue
        prices = getattr(bundle, "prices", None)
        p0 = _close_on(prices, entry)
        p1 = _close_on(prices, exit_)
        if p0 is None or p1 is None or p0 == 0.0:
            continue
        total += w * (p1 / p0 - 1.0)
    return total


def _empty_result(n_rebalances: int) -> dict:
    """The graceful short-circuit dict: metric fields ``None``, ``turnover`` 0."""
    out: dict = {k: None for k in _METRIC_KEYS}
    out["turnover"] = 0.0
    out["n_rebalances"] = n_rebalances
    return out


def backtest(bundles, config, sample: str) -> dict:
    """Score ``config`` on ``sample`` — monthly, long-only, fully-invested.

    Parameters
    ----------
    bundles
        ``{ticker: bundle}`` where each bundle exposes ``.prices`` (objects with
        ``.time`` / ``.close`` / ``.volume``) and ``.metrics_history`` — exactly
        what :func:`generate_holdings` consumes. Duck-typed (``SimpleNamespace``
        fakes work).
    config
        A :class:`~v2.self_evolve.config.StrategyConfig` (or any object exposing
        the fields ``generate_holdings`` reads, plus ``.rebalance``).
    sample
        One of :data:`v2.self_evolve.samples.SAMPLES` (``"train"`` / ``"val"`` /
        ``"test"``). Its fixed window bounds the rebalance calendar.

    Returns
    -------
    dict
        ``{"sharpe", "ann_return", "ann_vol", "max_drawdown", "turnover",
        "n_rebalances"}`` — see the module docstring for each field's convention.
        Never raises; degenerate inputs yield the graceful dict.
    """
    if not bundles:
        return _empty_result(0)

    # -- trading calendar: the sorted UNION of every bundle's price dates.
    day_set: set[str] = set()
    for bundle in bundles.values():
        for p in getattr(bundle, "prices", None) or []:
            t = getattr(p, "time", None)
            if isinstance(t, str) and len(t) >= 10:
                day_set.add(t[:10])
    trading_days = sorted(day_set)
    if not trading_days:
        return _empty_result(0)

    rebalance = getattr(config, "rebalance", "monthly") or "monthly"
    try:
        dates = rebalance_dates(sample, trading_days, freq=rebalance)
    except (KeyError, ValueError):
        # Unknown sample / unsupported freq → nothing to score, but never crash.
        return _empty_result(0)

    n_rebalances = len(dates)
    # Need at least two rebalance dates to form one held period.
    if n_rebalances < 2:
        return _empty_result(n_rebalances)

    # -- walk the rebalance dates: build a book on each, hold to the next, record
    # the period return and the turnover vs the previous book.
    period_returns: list[float] = []
    turnovers: list[float] = []
    prev_weights: dict[str, float] | None = None
    for i in range(n_rebalances - 1):
        entry, exit_ = dates[i], dates[i + 1]
        weights = generate_holdings(bundles, entry, config) or {}

        # One-way turnover vs the previous book (union of tickers; absent = 0 weight).
        if prev_weights is not None:
            names = set(weights) | set(prev_weights)
            l1 = sum(abs(weights.get(t, 0.0) - prev_weights.get(t, 0.0)) for t in names)
            turnovers.append(0.5 * l1)
        prev_weights = weights

        period_returns.append(_period_return(bundles, weights, entry, exit_))

    # -- compounded monthly equity curve with REAL datetime Dates. Point 0 is the
    # first rebalance date at START_CAPITAL; each subsequent point compounds one
    # period return and is stamped with that period's EXIT (next rebalance) date.
    curve: list[dict] = [{"Date": _dt.datetime.fromisoformat(dates[0]), "Portfolio Value": START_CAPITAL}]
    value = START_CAPITAL
    for i, r in enumerate(period_returns):
        value *= 1.0 + r
        curve.append({"Date": _dt.datetime.fromisoformat(dates[i + 1]), "Portfolio Value": value})

    # -- metrics. Build the calculator on the MONTHLY cadence so its sqrt-Sharpe
    # annualization and risk-free scaling are 12-period, not 252-period.
    metrics = PerformanceMetricsCalculator(annual_trading_days=PERIODS_PER_YEAR).compute_metrics(curve)
    sharpe = metrics.get("sharpe_ratio")
    # max_drawdown is ALREADY a percent (calculator ×100) — pass through AS-IS.
    max_drawdown = metrics.get("max_drawdown")

    # -- annualized return (geometric / CAGR) and annualized vol (period stdev).
    n_periods = len(period_returns)
    if value > 0.0 and n_periods > 0:
        ann_return = (value / START_CAPITAL) ** (PERIODS_PER_YEAR / n_periods) - 1.0
    else:
        # A wipeout (value <= 0) has no real geometric mean; report the floor.
        ann_return = -1.0 if n_periods > 0 else None
    ann_vol = statistics.pstdev(period_returns) * math.sqrt(PERIODS_PER_YEAR) if n_periods >= 2 else 0.0

    turnover = statistics.fmean(turnovers) if turnovers else 0.0

    return {
        "sharpe": sharpe,
        "ann_return": ann_return,
        "ann_vol": ann_vol,
        "max_drawdown": max_drawdown,
        "turnover": turnover,
        "n_rebalances": n_rebalances,
    }
