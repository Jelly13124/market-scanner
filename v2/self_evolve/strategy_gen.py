"""Config-driven portfolio construction — the deterministic output of the loop.

:func:`generate_holdings` turns the as-of factor scores from
:mod:`v2.self_evolve.factors` into a concrete long-only book: a
``{ticker: weight}`` mapping whose weights are positive and sum to ~1.0. It is
the fixed strategy KERNEL the self-evolve LLM tunes (via the bounded
:class:`~v2.self_evolve.config.StrategyConfig`) but never rewrites.

Pipeline (each step degrades gracefully — the function never raises):

1. **Liquidity filter.** Each ticker's trailing-``vol_days`` average *dollar*
   volume (``close * volume``) is computed as-of (bars dated ``<= asof``). Names
   below the ``liquidity_pct.advol_pct`` cross-sectional percentile are dropped.
   We have no shares-outstanding in the bundle, so market cap cannot be computed
   directly; we proxy it by the SAME average dollar volume and simply apply the
   STRICTER of the two declared percentiles (``mktcap_pct`` vs ``advol_pct``)
   rather than running two identical filters. A degenerate cross-section (≤2
   names, or every name at the same dollar volume) keeps ALL names rather than
   returning an empty book.

2. **Cross-sectional z-score.** For each factor the surviving values are
   z-scored across the cross-section. Per this repo's std-floor invariant, when
   the cross-sectional std is below :data:`STD_FLOOR` the factor contributes 0
   to every name (no divide-by-zero). ``value`` / ``quality`` that are ``None``
   (missing fundamentals) get a neutral 0 z — the name is NOT dropped.

3. **Composite.** ``Σ_f factor_weights[f] * zscore_f`` per surviving ticker.

4. **Select.** Rank by composite descending and keep the top ``top_n``.

5. **Vol-inverse weight.** ``weight_i ∝ 1 / max(vol_i, floor)`` where ``vol_i``
   is the trailing realized return stdev (the same measure the ``low_vol``
   factor is built on) — higher vol ⇒ lower weight. Weights are then capped at
   ``max_weight`` and renormalized to sum to 1.0, iterating so that a binding cap
   that spills onto the others can never push them back over the cap.

6. **Degenerate universe** (empty bundles, nobody with factors, …) → ``{}``.

Pure Python — no network, no pandas, no LLM. Reuses
:func:`v2.self_evolve.factors.compute_factors` for the factor matrix and mirrors
its as-of price extraction for the liquidity + vol measures.
"""

from __future__ import annotations

import logging
import statistics

from v2.self_evolve.config import FACTOR_KEYS
from v2.self_evolve.factors import _parse_iso, compute_factors

logger = logging.getLogger(__name__)

#: Cross-sectional std below this is treated as "collapsed" — the factor then
#: contributes 0 to every name instead of dividing by a ~0 std. The repo's
#: std-floor invariant: never fire only on std == 0.0 exactly.
STD_FLOOR = 1e-9

#: Floor on a single name's realized vol used in the inverse-vol weight, so a
#: (near-)zero-vol name does not blow its weight up to +inf. Relative scale only.
VOL_FLOOR = 1e-9

#: Default trailing window (in as-of BARS) for the liquidity dollar-volume and
#: the inverse-vol measures, used only if ``config.lookback`` lacks ``vol_days``.
DEFAULT_VOL_DAYS = 63


# ---------------------------------------------------------------------------
# As-of bar extraction (mirrors factors._asof_closes, but keeps volume too)
# ---------------------------------------------------------------------------


def _asof_bars(prices, asof: str) -> list[tuple[str, float, float]]:
    """``(date, close, volume)`` for bars dated ``<= asof``, ascending by date.

    The hard no-lookahead clamp: any bar dated after ``asof`` is dropped. Bars with
    an unparseable date or non-numeric close/volume are skipped (treated as absent).
    Missing volume defaults to 0.0 so a name with prices-but-no-volume is simply
    illiquid rather than a crash.
    """
    out: list[tuple[str, float, float]] = []
    for p in prices or []:
        d = _parse_iso(getattr(p, "time", None))
        if d is None or d > asof:
            continue
        close = getattr(p, "close", None)
        if not isinstance(close, (int, float)) or isinstance(close, bool):
            continue
        vol = getattr(p, "volume", None)
        if not isinstance(vol, (int, float)) or isinstance(vol, bool):
            vol = 0.0
        out.append((d, float(close), float(vol)))
    out.sort(key=lambda b: b[0])
    return out


def _avg_dollar_volume(bars: list[tuple[str, float, float]], vol_days: int) -> float:
    """Average ``close * volume`` over the trailing ``vol_days`` as-of bars.

    Returns 0.0 when there are no usable bars (the name then sorts to the bottom of
    the liquidity ranking and is dropped first).
    """
    window = bars[-vol_days:] if vol_days > 0 else bars
    if not window:
        return 0.0
    return sum(c * v for _, c, v in window) / len(window)


def _realized_vol(bars: list[tuple[str, float, float]], vol_days: int) -> float | None:
    """Population stdev of daily returns over the trailing ``vol_days`` bars.

    Mirrors the ``low_vol`` factor's vol measure (bar-count window, ``pstdev`` of
    simple returns). ``None`` when fewer than two returns are available — such a
    name cannot be vol-weighted and is handled by the caller (it falls back to the
    cross-sectional median vol so it is neither favoured nor crashed on).
    """
    window = bars[-(vol_days + 1) :] if vol_days > 0 else bars
    rets: list[float] = []
    for i in range(1, len(window)):
        prev = window[i - 1][1]
        if prev == 0.0:
            continue
        rets.append(window[i][1] / prev - 1.0)
    if len(rets) < 2:
        return None
    return statistics.pstdev(rets)


# ---------------------------------------------------------------------------
# Liquidity filter
# ---------------------------------------------------------------------------


def _liquidity_survivors(advol: dict[str, float], pct: float) -> set[str]:
    """Tickers at-or-above the ``pct`` cross-sectional percentile of dollar volume.

    Degenerate cases keep EVERYONE (never return empty): a ``pct <= 0`` filter, a
    universe of ≤2 names, or a cross-section where every name shares the same dollar
    volume (the percentile cut cannot meaningfully separate them). Otherwise drop the
    names strictly below the ``pct`` quantile threshold.
    """
    tickers = list(advol)
    if pct <= 0.0 or len(tickers) <= 2:
        return set(tickers)

    values = sorted(advol.values())
    if values[0] == values[-1]:  # all identical → degenerate, keep all
        return set(tickers)

    # Interpolated ``pct`` quantile (numpy-"linear"/type-7): position h = pct*(n-1),
    # threshold = linear interp between the two surrounding order statistics. This
    # avoids the int-truncation hole where e.g. int(0.20 * 4) == 0 would set the
    # threshold to the very smallest value and drop nobody. Keep advol >= threshold.
    n = len(values)
    h = pct * (n - 1)
    lo_i = int(h)
    frac = h - lo_i
    hi_i = min(lo_i + 1, n - 1)
    threshold = values[lo_i] + frac * (values[hi_i] - values[lo_i])
    survivors = {t for t, v in advol.items() if v >= threshold}
    # Guard: never return an empty universe (defensive — keep all if the cut somehow
    # excluded everyone).
    return survivors or set(tickers)


# ---------------------------------------------------------------------------
# Cross-sectional z-score
# ---------------------------------------------------------------------------


def _zscores(values: dict[str, float]) -> dict[str, float]:
    """Cross-sectional z-scores of ``values`` (std-floored to 0 contributions).

    With <2 names, or a cross-sectional std below :data:`STD_FLOOR`, EVERY name gets
    z = 0.0 — the factor simply does not differentiate (no divide-by-zero). This is
    the repo's std-floor invariant applied at the cross-section level.
    """
    if len(values) < 2:
        return {t: 0.0 for t in values}
    xs = list(values.values())
    mean = statistics.fmean(xs)
    std = statistics.pstdev(xs)
    if std < STD_FLOOR:
        return {t: 0.0 for t in values}
    return {t: (v - mean) / std for t, v in values.items()}


# ---------------------------------------------------------------------------
# Vol-inverse weighting with iterative cap + renormalize
# ---------------------------------------------------------------------------


def _cap_and_normalize(raw: dict[str, float], max_weight: float) -> dict[str, float]:
    """Normalize ``raw`` (positive) weights to sum 1.0 with a per-name cap.

    Iterative water-filling: pin every name that exceeds ``max_weight`` AT the cap,
    then redistribute the remaining mass proportionally among the uncapped names and
    repeat until no uncapped name breaches the cap. This is the correct fixed point —
    a single-pass cap can leave a name that absorbed spill-over back above the cap.

    If ``max_weight`` is too small to ever sum to 1.0 (``max_weight * n < 1``), the
    book saturates at all-capped (equal ``max_weight`` each); it then sums to
    ``max_weight * n < 1`` rather than violating the cap — the caller's config bounds
    keep ``max_weight`` sane (``>= 0.03`` with ``top_n <= 50`` ⇒ headroom), so this is
    only a defensive corner.
    """
    total = sum(raw.values())
    if total <= 0.0 or not raw:
        # No positive signal to weight on → fall back to equal weight.
        n = len(raw)
        return {t: 1.0 / n for t in raw} if n else {}

    weights = {t: w / total for t, w in raw.items()}
    capped: set[str] = set()
    for _ in range(len(weights) + 1):
        over = {t for t, w in weights.items() if w > max_weight + 1e-12 and t not in capped}
        if not over:
            break
        capped |= over
        for t in over:
            weights[t] = max_weight
        remaining = 1.0 - max_weight * len(capped)
        free = [t for t in weights if t not in capped]
        free_total = sum(raw[t] for t in free)
        if remaining <= 0.0 or free_total <= 0.0 or not free:
            # Cannot place more mass (everyone capped, or no headroom). Stop; the
            # book may sum to < 1.0 in this defensive corner.
            for t in free:
                weights[t] = 0.0 if remaining <= 0.0 else weights[t]
            break
        for t in free:
            weights[t] = remaining * raw[t] / free_total
    return weights


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_holdings(bundles, asof: str, config, *, cache=None) -> dict[str, float]:
    """Build the long-only, top-N, vol-inverse book for ``asof``.

    Parameters
    ----------
    bundles
        ``{ticker: bundle}`` where each bundle exposes ``.prices`` (objects with
        ``.time`` / ``.close`` / ``.volume``) and ``.metrics_history`` (see
        :func:`v2.self_evolve.factors.compute_factors`). Duck-typed — plain
        ``SimpleNamespace`` fakes work.
    asof
        Rebalance date (``YYYY-MM-DD...``); a hard no-lookahead ceiling.
    config
        A :class:`~v2.self_evolve.config.StrategyConfig` (or any object exposing
        ``.factor_weights`` / ``.top_n`` / ``.max_weight`` / ``.lookback`` /
        ``.liquidity_pct``).

    Returns
    -------
    dict
        ``{ticker: weight}`` with positive weights summing to ~1.0. Empty /
        degenerate universes return ``{}``. NEVER raises.
    """
    if not bundles:
        return {}
    asof_iso = _parse_iso(asof)
    if asof_iso is None:
        # M1: a non-ISO asof (e.g. a datetime.date — _parse_iso does asof[:10] and
        # returns None for a non-str) would otherwise yield a SILENT empty book,
        # indistinguishable from a legitimate no-signal week. Name the type so the
        # footgun is diagnosable instead of mute (see final review M1).
        logger.warning("generate_holdings: unparseable asof %r (type %s); returning empty book — pass an ISO 'YYYY-MM-DD' string", asof, type(asof).__name__)
        return {}

    lookback = getattr(config, "lookback", {}) or {}
    try:
        vol_days = int(lookback["vol_days"])
    except (KeyError, TypeError, ValueError):
        vol_days = DEFAULT_VOL_DAYS

    # -- as-of bars + per-name liquidity / vol measures (one extraction per name).
    bars_by_ticker: dict[str, list[tuple[str, float, float]]] = {}
    advol: dict[str, float] = {}
    for ticker, bundle in bundles.items():
        bars = _asof_bars(getattr(bundle, "prices", None), asof_iso)
        if not bars:
            continue
        bars_by_ticker[ticker] = bars
        advol[ticker] = _avg_dollar_volume(bars, vol_days)
    if not advol:
        return {}

    # -- liquidity filter. No shares → proxy market cap by the same dollar volume and
    # apply the STRICTER of the two declared percentiles (documented in module doc).
    liq = getattr(config, "liquidity_pct", {}) or {}
    advol_pct = float(liq.get("advol_pct", 0.0) or 0.0)
    mktcap_pct = float(liq.get("mktcap_pct", 0.0) or 0.0)
    pct = max(advol_pct, mktcap_pct)
    survivors = _liquidity_survivors(advol, pct)
    if not survivors:
        return {}

    # -- factor matrix for survivors only (compute_factors may omit short-history
    # names; those drop out here too).
    sub_bundles = {t: bundles[t] for t in survivors}
    factor_rows = compute_factors(sub_bundles, asof_iso, config, cache=cache)
    if not factor_rows:
        return {}

    # -- per-factor cross-sectional z-scores. None (missing fundamentals) → 0.0 so
    # the name keeps its price-factor contributions instead of being dropped.
    zmats: dict[str, dict[str, float]] = {}
    for f in FACTOR_KEYS:
        present = {t: row[f] for t, row in factor_rows.items() if isinstance(row.get(f), (int, float)) and not isinstance(row.get(f), bool)}
        zf = _zscores(present)
        zmats[f] = {t: zf.get(t, 0.0) for t in factor_rows}  # absent → neutral 0

    # -- composite = Σ weight_f * z_f.
    weights_cfg = getattr(config, "factor_weights", {}) or {}
    composite: dict[str, float] = {}
    for ticker in factor_rows:
        composite[ticker] = sum(float(weights_cfg.get(f, 0.0)) * zmats[f][ticker] for f in FACTOR_KEYS)

    # -- select top_n by composite (desc); ticker as a stable tiebreaker.
    top_n = int(getattr(config, "top_n", len(composite)))
    ranked = sorted(composite.items(), key=lambda kv: (-kv[1], kv[0]))
    selected = [t for t, _ in ranked[: max(top_n, 0)]]
    if not selected:
        return {}

    # -- vol-inverse raw weight: 1 / max(vol, floor). A name lacking a vol measure
    # falls back to the median selected vol (neither favoured nor penalised).
    vols: dict[str, float] = {}
    for t in selected:
        v = _realized_vol(bars_by_ticker[t], vol_days)
        if v is not None:
            vols[t] = v
    median_vol = statistics.median(vols.values()) if vols else VOL_FLOOR
    raw: dict[str, float] = {}
    for t in selected:
        v = vols.get(t, median_vol)
        raw[t] = 1.0 / max(v, VOL_FLOOR)

    return _cap_and_normalize(raw, float(getattr(config, "max_weight", 1.0)))
