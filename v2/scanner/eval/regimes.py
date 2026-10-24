"""SPY-based market-regime classifier for the scanner-evaluation harness.

The eval harness reports whether each detector/signal is useful in each market
regime. Regimes are derived purely from SPY price history: we slice the series
into named candidate windows and label each one BULL / BEAR / CHOPPY from its
total adjusted return, peak-to-trough drawdown, and the R^2 / sign of an OLS
trend fit on log-price.

Design notes:
    * Adjusted-close-preferred (via ``close_of``) so ex-div / split days don't
      manufacture fake moves.
    * Degenerate windows (< ~10 usable bars) are labelled CHOPPY with zeroed
      stats rather than crashing — a too-short slice can't be classified, and
      "no edge either way" is the safe default for a screener pre-filter.
    * The label is computed from the data, never from the candidate's *name*.
      If a window named ``choppy_2025`` measures as BULL we keep the BULL label
      and log a WARNING about the disagreement.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from v2.scanner.detectors.base import close_of

logger = logging.getLogger(__name__)

#: Below this many usable bars a window is treated as degenerate (CHOPPY, zeros).
_MIN_BARS = 10


@dataclass
class RegimeWindow:
    """One named SPY window with its measured regime statistics + label."""

    name: str  # candidate label, e.g. "bear_2022"
    start: str  # YYYY-MM-DD
    end: str  # YYYY-MM-DD
    spy_return: float  # total adjusted return over the window (e.g. -0.25)
    max_drawdown: float  # most-negative peak-to-trough, <= 0 (e.g. -0.18)
    trend_r2: float  # R^2 of OLS(log_close ~ time_index), 0..1
    n_bars: int
    label: str  # "BULL" | "BEAR" | "CHOPPY"


def _slice_closes(prices, start: str, end: str) -> list[float]:
    """Adjusted-close-preferred closes for bars in ``[start, end]``, ascending.

    Filters to bars whose ``time[:10]`` date prefix falls within the inclusive
    window, drops bars with no usable close, and sorts ascending by time.
    """
    rows = []
    for p in prices:
        day = (p.time or "")[:10]
        if start <= day <= end:
            c = close_of(p)
            if c is not None:
                rows.append((day, c))
    rows.sort(key=lambda r: r[0])
    return [c for _day, c in rows]


def _trend_r2_and_slope(closes: list[float]) -> tuple[float, float]:
    """R^2 and slope of OLS fit of ln(close) on the bar index 0..n-1.

    Returns ``(r2, slope)``. Guards: n < 2 → ``(0.0, 0.0)``; if ln(close) has
    zero variance (a perfectly flat line) the fit is exact-but-degenerate, so
    we report ``r2=0.0`` (no trend) with ``slope=0.0``.
    """
    n = len(closes)
    if n < 2:
        return 0.0, 0.0

    y = np.log(np.asarray(closes, dtype=float))
    x = np.arange(n, dtype=float)

    if float(np.std(y)) == 0.0:
        return 0.0, 0.0

    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    ss_res = float(np.sum((y - fitted) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    # Clamp tiny negative/overshoot from float error into [0, 1].
    r2 = max(0.0, min(1.0, r2))
    return r2, float(slope)


def _max_drawdown(closes: list[float]) -> float:
    """Most-negative peak-to-trough return over the series (<= 0)."""
    peak = closes[0]
    worst = 0.0
    for c in closes:
        if c > peak:
            peak = c
        if peak > 0:
            dd = c / peak - 1.0
            if dd < worst:
                worst = dd
    return worst


def classify_window(prices, *, name: str, start: str, end: str) -> RegimeWindow:
    """Measure + label one SPY window.

    See module docstring for the rationale. The label rule:

        BEAR  if spy_return <= -0.10 OR (max_drawdown <= -0.15 AND slope < 0)
        BULL  if spy_return >=  0.12 AND slope > 0 AND trend_r2 >= 0.5
        else  CHOPPY
    """
    closes = _slice_closes(prices, start, end)
    n = len(closes)

    if n < _MIN_BARS:
        # Degenerate: not enough bars to classify. CHOPPY + zeros, no crash.
        return RegimeWindow(
            name=name,
            start=start,
            end=end,
            spy_return=0.0,
            max_drawdown=0.0,
            trend_r2=0.0,
            n_bars=n,
            label="CHOPPY",
        )

    spy_return = closes[-1] / closes[0] - 1.0
    max_dd = _max_drawdown(closes)
    trend_r2, slope = _trend_r2_and_slope(closes)

    if spy_return <= -0.10 or (max_dd <= -0.15 and slope < 0):
        label = "BEAR"
    elif spy_return >= 0.12 and slope > 0 and trend_r2 >= 0.5:
        label = "BULL"
    else:
        label = "CHOPPY"

    return RegimeWindow(
        name=name,
        start=start,
        end=end,
        spy_return=spy_return,
        max_drawdown=max_dd,
        trend_r2=trend_r2,
        n_bars=n,
        label=label,
    )


#: The three recent default windows the eval harness reports on.
DEFAULT_CANDIDATES: list[dict] = [
    {"name": "bear_2022", "start": "2022-01-03", "end": "2022-10-14"},
    {"name": "bull_2023_24", "start": "2023-10-27", "end": "2024-07-16"},
    {"name": "choppy_2025", "start": "2025-02-18", "end": "2025-08-01"},
]


def _name_intent(name: str) -> str | None:
    """The regime a candidate's *name* implies, or None if ambiguous.

    Used only to surface a WARNING when the measured label disagrees with the
    human-chosen name — never to override the computed label.
    """
    low = name.lower()
    if "bear" in low:
        return "BEAR"
    if "bull" in low:
        return "BULL"
    if "choppy" in low or "chop" in low or "flat" in low:
        return "CHOPPY"
    return None


def classify_regimes(
    prices, candidates: list[dict] = DEFAULT_CANDIDATES
) -> list[RegimeWindow]:
    """Classify each candidate window; log stats at INFO, disagreements at WARNING.

    The computed label always wins. If a window's measured label contradicts the
    regime implied by its name, we keep the measured label and emit a WARNING so
    the candidate date ranges can be revisited.
    """
    out: list[RegimeWindow] = []
    for c in candidates:
        w = classify_window(prices, name=c["name"], start=c["start"], end=c["end"])
        logger.info(
            "regime %s [%s..%s]: label=%s return=%.3f max_dd=%.3f trend_r2=%.3f n_bars=%d",
            w.name,
            w.start,
            w.end,
            w.label,
            w.spy_return,
            w.max_drawdown,
            w.trend_r2,
            w.n_bars,
        )
        intent = _name_intent(w.name)
        if intent is not None and intent != w.label:
            logger.warning(
                "regime %s: name implies %s but measured %s (return=%.3f, "
                "max_dd=%.3f, trend_r2=%.3f) — keeping measured label",
                w.name,
                intent,
                w.label,
                w.spy_return,
                w.max_drawdown,
                w.trend_r2,
            )
        out.append(w)
    return out
