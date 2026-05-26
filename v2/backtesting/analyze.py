"""Post-hoc analysis of backtest CSV — rigor pass.

Reads a CSV produced by ``v2.backtesting.engine`` and produces a structured
console report covering:

  §1 Sample size + dedup metric (unique tickers, effective independent events)
  §2 Per-detector × per-window mean alpha with 95% bootstrap CI
  §3 BREAK split by horizons broken (63d-only / 63+126 / all-three)
  §4 INSDR strict subset (single-buy or cluster ≥2 with biggest_p_buy ≥ $250k)
  §5 Regime slicing (up / down / chop via SPY trailing 20d return)
  §6 Composite-rank quartile spread with CI

Point estimates without confidence intervals are misleading; this module
exists so every alpha number is reported with a bootstrap CI alongside,
and so detector subsetting / regime slicing happens consistently across
analyses.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
from scipy import stats as _scipy_stats

logger = logging.getLogger(__name__)


# Family-wise FDR target. Standard 5% — matches the bootstrap CI's 95%
# confidence so the two rigor knobs report at the same level.
FDR_ALPHA = 0.05


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


@dataclass
class Row:
    """One parsed CSV row — convenience over raw dict access in analyses."""

    scan_date: str
    ticker: str
    rank: int
    composite_score: float
    direction: str
    event_severity: float
    n_detectors_triggered: int
    triggered_detectors: list[str]
    triggered_components: dict[str, dict[str, float]]
    close_at_scan: float | None
    ret: dict[int, float | None]
    bench_ret: dict[int, float | None]
    alpha: dict[int, float | None]
    dir_ret_5d: float | None
    dir_alpha_5d: float | None


def _to_float(s: str | None) -> float | None:
    if s is None or s == "":
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _to_int(s: str | None, default: int = 0) -> int:
    if s is None or s == "":
        return default
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return default


def load_rows(csv_path: Path) -> list[Row]:
    """Parse the backtest CSV into Row objects."""
    out: list[Row] = []
    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            triggered = (raw.get("triggered_detectors") or "").split("|")
            triggered = [d for d in triggered if d]
            comps_raw = raw.get("triggered_components_json") or "{}"
            try:
                comps = json.loads(comps_raw)
            except json.JSONDecodeError:
                comps = {}
            ret = {n: _to_float(raw.get(f"ret_{n}d")) for n in (1, 5, 20, 63)}
            bench_ret = {n: _to_float(raw.get(f"bench_ret_{n}d")) for n in (1, 5, 20, 63)}
            alpha = {n: _to_float(raw.get(f"alpha_{n}d")) for n in (1, 5, 20, 63)}
            out.append(Row(
                scan_date=raw["scan_date"],
                ticker=raw["ticker"],
                rank=_to_int(raw["rank"]),
                composite_score=_to_float(raw["composite_score"]) or 0.0,
                direction=raw["direction"],
                event_severity=_to_float(raw["event_severity"]) or 0.0,
                n_detectors_triggered=_to_int(raw["n_detectors_triggered"]),
                triggered_detectors=triggered,
                triggered_components=comps,
                close_at_scan=_to_float(raw.get("close_at_scan")),
                ret=ret,
                bench_ret=bench_ret,
                alpha=alpha,
                dir_ret_5d=_to_float(raw.get("dir_ret_5d")),
                dir_alpha_5d=_to_float(raw.get("dir_alpha_5d")),
            ))
    return out


# ---------------------------------------------------------------------------
# Stats utilities
# ---------------------------------------------------------------------------


def _direction_adjust(value: float | None, direction: str) -> float | None:
    if value is None:
        return None
    if direction == "bearish":
        return -value
    return value


def bootstrap_ci(
    values: list[float], *, n_resamples: int = 5000, alpha: float = 0.05,
    seed: int = 42,
) -> tuple[float, float, float] | tuple[None, None, None]:
    """Return (mean, ci_low, ci_high) of ``values`` via percentile bootstrap.

    Empty input or single sample → all-None (no CI possible). Standard
    percentile method (no BCa correction) — good enough for the kind of
    moderate-skew alpha distributions we see in backtest output, fast for
    5k resamples.
    """
    if not values:
        return None, None, None
    n = len(values)
    if n < 2:
        return float(values[0]), None, None
    rng = np.random.default_rng(seed)
    arr = np.array(values, dtype=float)
    # vectorized resample
    idx = rng.integers(0, n, size=(n_resamples, n))
    sample_means = arr[idx].mean(axis=1)
    lo = float(np.percentile(sample_means, 100 * (alpha / 2)))
    hi = float(np.percentile(sample_means, 100 * (1 - alpha / 2)))
    return float(arr.mean()), lo, hi


def _fmt_pct(value: float | None, *, sign: bool = True) -> str:
    if value is None:
        return "—"
    fmt = f"{value*100:+.2f}%" if sign else f"{value*100:.2f}%"
    return fmt


def _fmt_ci(values: list[float], *, n_resamples: int) -> str:
    """Format '+0.42% [-0.34%, +1.18%] (n=60)' style string."""
    mean, lo, hi = bootstrap_ci(values, n_resamples=n_resamples)
    if mean is None:
        return "—"
    if lo is None or hi is None:
        return f"{_fmt_pct(mean)} (n={len(values)})"
    return f"{_fmt_pct(mean):>7s}  [{_fmt_pct(lo):>7s}, {_fmt_pct(hi):>7s}]  n={len(values)}"


def _raw_pvalue(values: list[float]) -> float | None:
    """Two-sided one-sample t-test against H0: mean = 0. Returns None for
    samples too small to have a defined p-value (need n ≥ 2 with positive
    variance). Used as the input to BH FDR control across (detector × window)
    families.
    """
    if not values or len(values) < 2:
        return None
    arr = np.asarray(values, dtype=float)
    if not np.isfinite(arr).all():
        arr = arr[np.isfinite(arr)]
        if len(arr) < 2:
            return None
    # Tolerance — float subtraction makes std([0.05, 0.05, 0.05]) a tiny
    # non-zero number rather than exact zero, which produces a meaningless
    # ~1e-33 p-value from scipy.
    if arr.std(ddof=1) < 1e-12:
        return None
    res = _scipy_stats.ttest_1samp(arr, popmean=0.0)
    p = float(res.pvalue)
    return p if np.isfinite(p) else None


def _bh_adjust(p_values: list[float | None]) -> list[float | None]:
    """Benjamini-Hochberg FDR-adjusted p-values, preserving input order +
    Nones. Uses ``scipy.stats.false_discovery_control`` (scipy ≥ 1.11)
    which returns the adjusted "q-values" suitable for comparing to a
    single FDR level (e.g. 0.05).
    """
    finite_idx = [i for i, p in enumerate(p_values) if p is not None]
    if not finite_idx:
        return [None] * len(p_values)
    finite_p = np.array([p_values[i] for i in finite_idx], dtype=float)
    adjusted_finite = _scipy_stats.false_discovery_control(finite_p, method="bh")
    out: list[float | None] = [None] * len(p_values)
    for i, adj in zip(finite_idx, adjusted_finite):
        out[i] = float(adj)
    return out


# ---------------------------------------------------------------------------
# §1 Sample size + dedup
# ---------------------------------------------------------------------------


def _independence_check(
    rows: list[Row], *, min_gap_days: int = 5,
) -> tuple[int, list[tuple[str, list[str]]]]:
    """Count (ticker, scan_date) pairs where the same ticker hasn't appeared
    within the previous ``min_gap_days`` trading days. The result is the
    effective n for non-overlapping ``min_gap_days``-day return windows —
    e.g. for 5d alpha, repeated picks of PDD on consecutive days are NOT
    independent samples.

    Also returns per-ticker (ticker, included_scan_dates) for top inspection.
    """
    # Group by ticker, sort by scan_date, walk through keeping events that
    # are at least ``min_gap_days`` calendar days after the last KEPT event.
    # Trading-day approximation: use calendar days ≥ 7 as a conservative
    # proxy for 5 trading days (covers a weekend). Slight overcount of
    # independence is fine for a sanity stat.
    cal_gap = min_gap_days + 2  # weekend buffer
    by_ticker: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        by_ticker[r.ticker].append(r.scan_date)

    independent_n = 0
    per_ticker: list[tuple[str, list[str]]] = []
    for tk in by_ticker:
        dates = sorted(set(by_ticker[tk]))
        kept: list[str] = []
        last_kept: datetime | None = None
        for d in dates:
            d_dt = datetime.strptime(d, "%Y-%m-%d")
            if last_kept is None or (d_dt - last_kept).days >= cal_gap:
                kept.append(d)
                last_kept = d_dt
        independent_n += len(kept)
        per_ticker.append((tk, kept))
    return independent_n, per_ticker


def report_sample_size(rows: list[Row], *, min_gap_days: int = 5) -> None:
    """§1: total / unique tickers / top dominators / effective independent n."""
    print()
    print("=" * 78)
    print("§1  SAMPLE SIZE + INDEPENDENCE")
    print("=" * 78)

    total = len(rows)
    unique_tickers = len({r.ticker for r in rows})
    unique_scans = len({r.scan_date for r in rows})
    print(f"Total entries:                  {total}")
    print(f"Unique scan_dates:              {unique_scans}")
    print(f"Unique tickers:                 {unique_tickers}")

    # Per-ticker entry-count distribution
    per_t = defaultdict(int)
    for r in rows:
        per_t[r.ticker] += 1
    counts = sorted(per_t.values(), reverse=True)
    median = counts[len(counts) // 2] if counts else 0
    print(f"Per-ticker count median:        {median}")
    print(f"Per-ticker count max:           {counts[0] if counts else 0}")

    # Top 10 dominators
    print()
    print("Top 10 most-appearing tickers (sample dominators):")
    print(f"  {'ticker':<8s} {'entries':>8s}  {'pct of total':>14s}")
    top = sorted(per_t.items(), key=lambda kv: kv[1], reverse=True)[:10]
    for tk, n in top:
        print(f"  {tk:<8s} {n:>8d}  {n/total*100:>13.1f}%")

    # Effective independent events at 5-trading-day spacing
    indep_n, _ = _independence_check(rows, min_gap_days=min_gap_days)
    ratio = indep_n / total if total else 0.0
    print()
    print(
        f"Effective independent events (≥{min_gap_days} trading days apart): "
        f"{indep_n} / {total} = {ratio*100:.1f}%"
    )
    print(
        "  → use this as effective n when judging 5d-window-based statistics. "
        "If this is much smaller than total, alpha standard errors are "
        "wider than naive √n suggests."
    )


# ---------------------------------------------------------------------------
# §2 Per-detector × per-window with bootstrap CI
# ---------------------------------------------------------------------------


def report_per_detector(
    rows: list[Row], *, n_resamples: int = 5000,
) -> None:
    """§2: for each detector that co-fired on at least one entry, compute
    mean dir-adjusted alpha + 95% CI for each forward window.

    Adds two extra columns: the raw two-sided one-sample t-test p-value
    (H0: alpha=0) and a Benjamini-Hochberg FDR-adjusted p-value computed
    over the FULL (detector × window) family. A trailing ``*`` marks
    rows with adjusted p < FDR_ALPHA so the eye can scan for survivors.
    """
    print()
    print("=" * 78)
    print(f"§2  PER-DETECTOR × WINDOW (dir-adjusted alpha, {n_resamples} bootstrap resamples,")
    print(f"     BH FDR over all detector × window pairs @ α={FDR_ALPHA})")
    print("=" * 78)

    per_det_alpha: dict[str, dict[int, list[float]]] = defaultdict(
        lambda: {1: [], 5: [], 20: [], 63: []}
    )
    for r in rows:
        for d in r.triggered_detectors:
            for n in (1, 5, 20, 63):
                a = _direction_adjust(r.alpha[n], r.direction)
                if a is not None:
                    per_det_alpha[d][n].append(a)

    if not per_det_alpha:
        print("(no detectors fired in this CSV)")
        return

    # Collect raw p-values across every (detector, window) cell first so
    # the BH adjustment uses the full family-of-tests size.
    cells: list[tuple[str, int, list[float], float | None]] = []
    for det in sorted(per_det_alpha):
        for n in (1, 5, 20, 63):
            vals = per_det_alpha[det][n]
            cells.append((det, n, vals, _raw_pvalue(vals)))
    fdr_adjusted = _bh_adjust([c[3] for c in cells])

    # Index for quick (det, n) → (p_raw, p_fdr, sig) lookup.
    lookup: dict[tuple[str, int], tuple[float | None, float | None, bool]] = {}
    for (det, n, _vals, p_raw), p_fdr in zip(cells, fdr_adjusted):
        sig = p_fdr is not None and p_fdr < FDR_ALPHA
        lookup[(det, n)] = (p_raw, p_fdr, sig)

    for det in sorted(per_det_alpha):
        windows = per_det_alpha[det]
        print()
        print(f"  {det}")
        print(f"    {'window':<8s}  {'mean':>7s}  {'95% CI':>20s}  {'n':>6s}  "
              f"{'p_raw':>8s}  {'p_fdr':>8s}  sig")
        for n in (1, 5, 20, 63):
            ci_line = _fmt_ci(windows[n], n_resamples=n_resamples)
            p_raw, p_fdr, sig = lookup[(det, n)]
            p_raw_s = f"{p_raw:.4f}" if p_raw is not None else "—"
            p_fdr_s = f"{p_fdr:.4f}" if p_fdr is not None else "—"
            sig_s = "*" if sig else ""
            print(f"    {n:>3d}d      {ci_line}  {p_raw_s:>8s}  {p_fdr_s:>8s}  {sig_s}")


# ---------------------------------------------------------------------------
# §3 BREAK by horizon
# ---------------------------------------------------------------------------


def _break_horizons_for(row: Row) -> list[int] | None:
    """Return the list of horizons broken on this entry, or None when BREAK
    didn't fire. Reads components.breakout_52w (stable name kept for DB
    compat — file is breakout_multi_horizon.py).

    Two possible component shapes from the detector:
      * ``horizons_broken`` direct list (preferred path)
      * fallback: parse from ``n_bullish_horizons`` + ``n_bearish_horizons``
        + ``hi_63d``/``lo_63d`` etc. — but the detector currently exposes
        the explicit list, so the fallback is only for forward-compat.
    """
    comp = row.triggered_components.get("breakout_52w")
    if not comp:
        return None
    # Look for direct list first
    if "horizons_broken" in comp and isinstance(comp["horizons_broken"], list):
        return [int(h) for h in comp["horizons_broken"]]
    # Reconstruct from per-horizon hi/lo presence — every horizon dict key
    # gets populated when the detector evaluated it, but only the FIRED
    # ones make it into the breakout count.
    # Component values are all stored as floats in our schema; n_bullish
    # and n_bearish tell us total but not WHICH horizons. Best-effort:
    n_bull = int(comp.get("n_bullish_horizons", 0))
    n_bear = int(comp.get("n_bearish_horizons", 0))
    if n_bull == 0 and n_bear == 0:
        return []
    # The detector picks bullish if n_bull >= n_bear (and at least one
    # bullish), so we can map by count. Horizons fire in ascending order
    # for a clean breakout (63d fires first, then 126d, then 252d).
    n = max(n_bull, n_bear)
    if n == 1:
        return [63]
    if n == 2:
        return [63, 126]
    if n >= 3:
        return [63, 126, 252]
    return []


def report_break_horizon_split(
    rows: list[Row], *, n_resamples: int = 5000,
) -> None:
    """§3: split BREAK-firing entries by which horizon set was broken;
    report alpha + CI per group across multiple forward windows."""
    print()
    print("=" * 78)
    print("§3  BREAK BY HORIZON (dir-adjusted alpha)")
    print("=" * 78)

    bucket_alphas: dict[str, dict[int, list[float]]] = {
        "63d only":            {5: [], 20: [], 63: []},
        "63d + 126d":          {5: [], 20: [], 63: []},
        "63d + 126d + 252d":   {5: [], 20: [], 63: []},
    }
    bucket_counts: dict[str, int] = defaultdict(int)

    for r in rows:
        horizons = _break_horizons_for(r)
        if horizons is None:
            continue
        if set(horizons) == {63}:
            bucket = "63d only"
        elif set(horizons) == {63, 126}:
            bucket = "63d + 126d"
        elif set(horizons) >= {63, 126, 252}:
            bucket = "63d + 126d + 252d"
        else:
            continue  # rare shape (e.g. 126-only) — skip
        bucket_counts[bucket] += 1
        for n in (5, 20, 63):
            a = _direction_adjust(r.alpha[n], r.direction)
            if a is not None:
                bucket_alphas[bucket][n].append(a)

    print(f"  {'bucket':<22s}  {'window':<6s}  {'mean':>8s}  {'95% CI':>22s}  {'n':>5s}")
    for bucket in ("63d only", "63d + 126d", "63d + 126d + 252d"):
        for n in (5, 20, 63):
            vals = bucket_alphas[bucket][n]
            line = _fmt_ci(vals, n_resamples=n_resamples)
            print(f"  {bucket:<22s}  {n:>3d}d     {line}")

    print()
    print(
        "  Interpretation: rising mean across buckets supports momentum "
        "interpretation (more horizons broken = stronger trend). Flat or "
        "decreasing suggests anchoring (only the 63d level matters)."
    )


# ---------------------------------------------------------------------------
# §4 INSDR strict subset
# ---------------------------------------------------------------------------


def report_insdr_strict(
    rows: list[Row], *, min_dollars: float = 250_000.0,
    n_resamples: int = 5000,
) -> None:
    """§4: contrast (a) all INSDR triggers vs (b) the strict subset that
    looks like a true informed buy — either a single-buy path with
    biggest_p_buy_abs ≥ min_dollars (P-coded), OR a cluster with ≥2
    distinct buyers AND biggest_p_buy_abs ≥ min_dollars.
    """
    print()
    print("=" * 78)
    print(f"§4  INSDR STRICT FILTER (informed buy: ≥${int(min_dollars):,} P-buy)")
    print("=" * 78)

    all_insdr_alpha: dict[int, list[float]] = {5: [], 20: [], 63: []}
    strict_buy_alpha: dict[int, list[float]] = {5: [], 20: [], 63: []}
    insdr_sell_alpha: dict[int, list[float]] = {5: [], 20: [], 63: []}

    for r in rows:
        comp = r.triggered_components.get("insider_cluster")
        if not comp:
            continue
        single_buy = bool(comp.get("direction_path_single_buy", 0.0) >= 1.0)
        cluster_path = bool(comp.get("direction_path_cluster", 0.0) >= 1.0)
        recent_buyers = int(comp.get("recent_buyers", 0))
        recent_sellers = int(comp.get("recent_sellers", 0))
        biggest_p = float(comp.get("biggest_p_buy_abs", 0.0))

        is_strict_buy = (
            single_buy and biggest_p >= min_dollars
        ) or (
            cluster_path and r.direction == "bullish"
            and recent_buyers >= 2 and biggest_p >= min_dollars
        )
        is_sell = r.direction == "bearish"

        for n in (5, 20, 63):
            a = _direction_adjust(r.alpha[n], r.direction)
            if a is None:
                continue
            all_insdr_alpha[n].append(a)
            if is_strict_buy:
                strict_buy_alpha[n].append(a)
            if is_sell:
                insdr_sell_alpha[n].append(a)

    if not all_insdr_alpha[5]:
        print("  (no INSDR entries in CSV)")
        return

    print(f"  {'subset':<22s}  {'window':<6s}  {'mean':>8s}  {'95% CI':>22s}  {'n':>5s}")
    for label, bucket in [
        ("All INSDR", all_insdr_alpha),
        ("Strict P-buy ≥$250k", strict_buy_alpha),
        ("INSDR sell side", insdr_sell_alpha),
    ]:
        for n in (5, 20, 63):
            line = _fmt_ci(bucket[n], n_resamples=n_resamples)
            print(f"  {label:<22s}  {n:>3d}d     {line}")

    print()
    print(
        "  Interpretation: if strict buy CI is well above 0 and separated "
        "from all-INSDR CI, the asymmetric thresholds (≥2 buyers + ≥$250k P) "
        "isolate the real informed-trade signal."
    )


# ---------------------------------------------------------------------------
# §5 Regime slicing via SPY trailing 20d return
# ---------------------------------------------------------------------------


def _build_regime_map(
    scan_dates: list[str], *, threshold: float, fd_factory: Callable | None = None,
    benchmark_ticker: str = "SPY",
    spy_prices_override: list | None = None,
) -> dict[str, str]:
    """For each unique scan_date, compute SPY's trailing 20-trading-day
    return AS OF that date and classify the regime:

        up:    trailing_20d >  +threshold
        down:  trailing_20d <  -threshold
        chop:  in between

    ``spy_prices_override`` lets tests inject a deterministic Price list
    without going through the network.
    """
    if not scan_dates:
        return {}

    unique_dates = sorted(set(scan_dates))
    start = unique_dates[0]
    # Pull SPY from ~35 calendar days before start to cover the 20-trading-day
    # trailing window even at the start of the backtest range.
    fetch_start = (
        datetime.strptime(start, "%Y-%m-%d") - timedelta(days=40)
    ).date().isoformat()

    if spy_prices_override is not None:
        bars = spy_prices_override
    else:
        if fd_factory is None:
            from v2.data.factory import get_provider_factory
            fd_factory = get_provider_factory()
        client = fd_factory()
        try:
            bars = client.get_prices(benchmark_ticker, fetch_start, unique_dates[-1])
        finally:
            try:
                client.close()
            except Exception:
                pass

    if not bars:
        return {}

    # Build {date_str -> close} dict, sorted ascending
    bars_sorted = sorted(bars, key=lambda p: p.time[:10])
    closes_by_date: list[tuple[str, float]] = []
    for p in bars_sorted:
        c = float(p.adjusted_close if p.adjusted_close is not None else p.close)
        if c > 0:
            closes_by_date.append((p.time[:10], c))

    if len(closes_by_date) < 21:
        return {}

    # For each scan_date, find the closest SPY bar ≤ scan_date and look
    # back 20 trading bars.
    regime: dict[str, str] = {}
    for sd in unique_dates:
        # Find idx of last bar with date ≤ sd
        idx = -1
        for i, (d, _) in enumerate(closes_by_date):
            if d <= sd:
                idx = i
            else:
                break
        if idx < 20:
            continue  # not enough trailing data
        trailing = (closes_by_date[idx][1] / closes_by_date[idx - 20][1]) - 1.0
        if trailing > threshold:
            regime[sd] = "up"
        elif trailing < -threshold:
            regime[sd] = "down"
        else:
            regime[sd] = "chop"
    return regime


def report_regime_slice(
    rows: list[Row], *, threshold: float = 0.01, n_resamples: int = 5000,
    regime_map: dict[str, str] | None = None,
) -> None:
    """§5: classify each scan_date into up/down/chop using SPY 20d trailing
    return, then per (regime × detector) report mean dir-alpha + CI."""
    print()
    print("=" * 78)
    print(f"§5  REGIME SLICING (SPY 20d trailing, threshold=±{threshold*100:.1f}%)")
    print("=" * 78)

    if regime_map is None:
        scan_dates = [r.scan_date for r in rows]
        regime_map = _build_regime_map(scan_dates, threshold=threshold)

    if not regime_map:
        print("  (could not build regime map — SPY fetch failed or insufficient history)")
        return

    # Print regime calendar summary
    regime_counts: dict[str, int] = defaultdict(int)
    for sd, reg in regime_map.items():
        regime_counts[reg] += 1
    print(
        f"  Regime calendar: up={regime_counts.get('up', 0)} days, "
        f"chop={regime_counts.get('chop', 0)} days, "
        f"down={regime_counts.get('down', 0)} days "
        f"(of {len(regime_map)} scan dates classified)"
    )

    per_regime_det: dict[tuple[str, str], list[float]] = defaultdict(list)
    overall_per_regime: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        reg = regime_map.get(r.scan_date)
        if reg is None:
            continue
        a = _direction_adjust(r.alpha[5], r.direction)
        if a is None:
            continue
        overall_per_regime[reg].append(a)
        for d in r.triggered_detectors:
            per_regime_det[(reg, d)].append(a)

    print()
    print("  Overall (all entries) by regime — 5d dir-alpha:")
    print(f"    {'regime':<8s}  {'mean':>8s}  {'95% CI':>22s}  {'n':>5s}")
    for reg in ("up", "chop", "down"):
        line = _fmt_ci(overall_per_regime[reg], n_resamples=n_resamples)
        print(f"    {reg:<8s}   {line}")

    # Per-detector × regime grid (consistent cell widths so columns align)
    detectors = sorted({d for (_, d) in per_regime_det.keys()})
    if detectors:
        cell_width = 18
        print()
        print("  Per-detector × regime — 5d dir-alpha (mean only; CI runs O(n) per cell):")
        header = "    {:<22s}".format("detector") + "".join(
            f"  {reg:>{cell_width}s}" for reg in ("up", "chop", "down")
        )
        print(header)
        for det in detectors:
            row_parts = ["    {:<22s}".format(det)]
            for reg in ("up", "chop", "down"):
                vals = per_regime_det.get((reg, det), [])
                if not vals:
                    cell = "—"
                else:
                    mean_pct = sum(vals) / len(vals) * 100
                    cell = f"{mean_pct:+.2f}% (n={len(vals)})"
                row_parts.append(f"  {cell:>{cell_width}s}")
            print("".join(row_parts))

    print()
    print(
        "  Interpretation: detectors with similar performance across regimes "
        "are robust; those that work only in 'up' (e.g. momentum-style) or "
        "only in 'down' (e.g. contrarian) are regime-dependent."
    )


# ---------------------------------------------------------------------------
# §6 Composite-rank quartile spread
# ---------------------------------------------------------------------------


def report_composite_quartiles(
    rows: list[Row], *, top_n: int = 20, n_resamples: int = 5000,
) -> None:
    """§6: bucket entries by within-day rank (1-5 / 6-10 / 11-15 / 16-20)
    and report dir-adjusted alpha + CI per bucket. The KEY test that
    composite score does what it claims: top picks should outperform
    bottom picks by a statistically meaningful margin."""
    print()
    print("=" * 78)
    print("§6  COMPOSITE RANK QUARTILES (does the score sort signal from noise?)")
    print("=" * 78)

    buckets: dict[str, list[float]] = {
        "Rank 1-5":   [],
        "Rank 6-10":  [],
        "Rank 11-15": [],
        "Rank 16-20": [],
    }
    for r in rows:
        a = _direction_adjust(r.alpha[5], r.direction)
        if a is None:
            continue
        if 1 <= r.rank <= 5:
            buckets["Rank 1-5"].append(a)
        elif 6 <= r.rank <= 10:
            buckets["Rank 6-10"].append(a)
        elif 11 <= r.rank <= 15:
            buckets["Rank 11-15"].append(a)
        elif 16 <= r.rank <= 20:
            buckets["Rank 16-20"].append(a)

    print(f"  {'bucket':<12s}  {'mean':>8s}  {'95% CI':>22s}  {'n':>5s}")
    for label in ("Rank 1-5", "Rank 6-10", "Rank 11-15", "Rank 16-20"):
        line = _fmt_ci(buckets[label], n_resamples=n_resamples)
        print(f"  {label:<12s}    {line}")

    # Top-vs-bottom spread (with simple subtraction; for a real CI on the
    # difference we'd need paired bootstrap. Single number for now).
    if buckets["Rank 1-5"] and buckets["Rank 16-20"]:
        top_mean = sum(buckets["Rank 1-5"]) / len(buckets["Rank 1-5"])
        bot_mean = sum(buckets["Rank 16-20"]) / len(buckets["Rank 16-20"])
        print()
        print(f"  Top - Bottom spread (5d dir-alpha): {_fmt_pct(top_mean - bot_mean)}")


# ---------------------------------------------------------------------------
# CLI scaffolding — final sections wired in main() below.
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    # SPY fetch (regime slicing §5) needs provider credentials — mirror
    # the engine CLI's load_dotenv behavior so notebook / direct callers
    # don't fail with 401.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    parser = argparse.ArgumentParser(
        prog="python -m v2.backtesting.analyze",
        description="Post-hoc analysis of a backtest CSV.",
    )
    parser.add_argument("csv", type=Path, help="Backtest CSV produced by v2.backtesting.engine")
    parser.add_argument(
        "--bootstrap-n", type=int, default=5000,
        help="Bootstrap resamples for CIs (default: 5000).",
    )
    parser.add_argument(
        "--regime-thresh", type=float, default=0.01,
        help="SPY 20d trailing return threshold for up/down regime (default: 0.01 = 1%%).",
    )
    parser.add_argument(
        "--insdr-min-dollars", type=float, default=250_000.0,
        help="Minimum $ size for strict INSDR P-buy filter (default: 250000).",
    )
    parser.add_argument(
        "--min-gap-days", type=int, default=5,
        help="Min trading days between repeated picks for independence count (default: 5).",
    )
    parser.add_argument("--output", type=Path, default=None,
                        help="If set, also write the report to this file.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.csv.exists():
        parser.error(f"CSV not found: {args.csv}")

    rows = load_rows(args.csv)
    if not rows:
        print(f"WARNING: CSV is empty: {args.csv}")
        return 1

    # Buffer report so --output mirrors what's on-screen.
    from io import StringIO
    buffer = StringIO()
    import contextlib
    with contextlib.redirect_stdout(buffer):
        report_sample_size(rows, min_gap_days=args.min_gap_days)
        report_per_detector(rows, n_resamples=args.bootstrap_n)
        report_break_horizon_split(rows, n_resamples=args.bootstrap_n)
        report_insdr_strict(
            rows, min_dollars=args.insdr_min_dollars, n_resamples=args.bootstrap_n,
        )
        report_regime_slice(
            rows, threshold=args.regime_thresh, n_resamples=args.bootstrap_n,
        )
        report_composite_quartiles(rows, n_resamples=args.bootstrap_n)

    text = buffer.getvalue()
    print(text)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"\nReport also written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
