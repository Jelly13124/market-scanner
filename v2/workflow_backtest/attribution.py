"""Forward-return attribution + A/B Welch t-test for workflow backtests.

Two pieces:

  * ``attach_forward_returns`` — for each DIRECTIONAL decision (buy → long,
    short → short), compute what the ticker actually did over the forward
    windows (raw return, benchmark return, alpha) by reusing
    ``compute_forward_returns``, then derive the direction-adjusted SIGNAL
    return (``side * ret``) so a correct short on a falling stock scores as
    a win. The fd passed here is the UNCLAMPED full-series client so OUTCOMES
    aren't clipped to the as-of date (the caller deliberately passes a
    non-as-of fd).

  * ``ab_welch`` — Welch two-sample t-test (unequal variances) comparing
    two arms' return distributions (e.g. scanner picks vs random baseline).
    Hand-rolled on the stdlib so we don't pull in scipy.
"""

from __future__ import annotations

import math
import statistics

from v2.backtesting.forward_returns import compute_forward_returns


def ab_welch(a, b):
    """Welch two-sample t (unequal variances).

    Returns ``{"mean_a","mean_b","diff","t","n_a","n_b"}`` where
    ``diff = mean_a - mean_b`` and
    ``t = diff / sqrt(var_a/n_a + var_b/n_b)`` (sample variance, ddof=1).

    None entries are dropped from each list before computing. Means/diff
    are computed when n>=1 (else None); ``t`` is None unless both n_a>=2
    and n_b>=2 (variance is undefined for n<2).
    """
    aa = [x for x in a if x is not None]
    bb = [x for x in b if x is not None]
    n_a, n_b = len(aa), len(bb)
    mean_a = statistics.mean(aa) if aa else None
    mean_b = statistics.mean(bb) if bb else None
    diff = (mean_a - mean_b) if (mean_a is not None and mean_b is not None) else None
    t = None
    if n_a >= 2 and n_b >= 2:
        va = statistics.variance(aa)
        vb = statistics.variance(bb)
        denom = math.sqrt(va / n_a + vb / n_b)
        t = (diff / denom) if denom > 0 else 0.0
    return {"mean_a": mean_a, "mean_b": mean_b, "diff": diff, "t": t, "n_a": n_a, "n_b": n_b}


_SIDE_BY_ACTION = {"buy": 1, "short": -1}


def attach_forward_returns(decisions, fd, *, scan_date, windows=(21, 42, 63),
                           benchmark_ticker="SPY", benchmark_prices=None):
    """Attach realized forward returns to each DIRECTIONAL decision.

    A decision is a directional bet iff ``action in {"buy", "short"}``:
    ``buy`` → ``side=+1`` (long), ``short`` → ``side=-1`` (short).
    ``hold``/``sell``/``cover`` are NOT opening bets and are skipped.

    For each bet, call ``compute_forward_returns`` and emit a row::

        {"ticker", "scan_date", "action", "side", "confidence",
         **fwd_return_dict, "signal_ret_{N}d": side * ret_{N}d, ...}

    The SIGNAL return is the direction-adjusted realized return — a correct
    short on a -5% move scores +5% — so the A/B credits good directional
    calls, long OR short. ``fd`` should be the UNCLAMPED full-series client so
    forward OUTCOMES aren't truncated to the scan_date (intentional asymmetry
    vs the as-of fd used for the signal).
    """
    rows = []
    for d in decisions:
        side = _SIDE_BY_ACTION.get(getattr(d, "action", None))
        if side is None:
            continue
        fr = compute_forward_returns(fd, ticker=d.ticker, scan_date=scan_date, windows=windows,
                                     benchmark_ticker=benchmark_ticker, benchmark_prices=benchmark_prices)
        row = {"ticker": d.ticker, "scan_date": scan_date, "action": d.action,
               "side": side, "confidence": getattr(d, "confidence", None), **fr}
        for n in windows:
            ret = fr.get(f"ret_{n}d")
            row[f"signal_ret_{n}d"] = (side * ret) if ret is not None else None
        rows.append(row)
    return rows
