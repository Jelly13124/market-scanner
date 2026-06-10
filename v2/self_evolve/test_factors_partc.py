"""Part-C price/volume factors — ``max_lottery`` / ``high_52w`` / ``turnover``.

These three factors are computed AS-OF each rebalance date with the same hard
no-lookahead ceiling as the Part-B factors: only bars dated ``<= asof`` may enter
the math. Each test pins (a) a known value on a crafted synthetic bundle, (b) the
no-lookahead clamp (a huge post-asof spike / volume must NOT move the value), and
(c) the per-factor ``None`` degradation (missing/insufficient data → that factor is
``None`` while the ticker keeps its other factors).

Signs are baked so HIGHER z = BETTER:

* ``max_lottery`` = ``-max(daily return over the last max_days as-of bars)`` — a big
  recent up-spike (lottery-like) is penalised (more negative).
* ``high_52w``    = ``close[asof] / max(close over last hi_days bars)`` — near the
  rolling high → ≈ 1.0 (strong); far below → small.
* ``turnover``    = ``-(mean(vol last to_days) / mean(vol full as-of series))`` —
  elevated recent volume → more negative (penalised).

Offline, pure-Python: synthetic ``SimpleNamespace`` fakes, no network / data / LLM.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from v2.self_evolve.factors import compute_factors


# ---------------------------------------------------------------------------
# Synthetic-bundle builders
# ---------------------------------------------------------------------------


def _price(d: str, close: float, volume: float | None = 1_000_000.0) -> SimpleNamespace:
    """A bar with ``.time`` / ``.close`` and (optionally) ``.volume``.

    Passing ``volume=None`` produces a bar WITHOUT a usable volume (the attribute is
    present but non-numeric), exercising the turnover-missing-data path.
    """
    return SimpleNamespace(time=d, close=close, volume=volume)


def _no_vol_price(d: str, close: float) -> SimpleNamespace:
    """A bar with NO ``.volume`` attribute at all (getattr → None)."""
    return SimpleNamespace(time=d, close=close)


def _config(*, momentum_days=180, vol_days=30, reversal_days=10, max_days=21, hi_days=252, to_days=21) -> SimpleNamespace:
    """A minimal stand-in for ``StrategyConfig`` — only ``.lookback`` is read."""
    return SimpleNamespace(
        lookback={
            "momentum_days": momentum_days,
            "vol_days": vol_days,
            "reversal_days": reversal_days,
            "max_days": max_days,
            "hi_days": hi_days,
            "to_days": to_days,
        }
    )


def _flat_bars(start: date, n: int, *, close: float = 100.0, volume: float = 1_000_000.0) -> list[SimpleNamespace]:
    """``n`` consecutive calendar-day bars, constant close and volume.

    Calendar-day bars keep offset arithmetic trivial: ``compute_factors`` snaps each
    target to the nearest bar at-or-before it, which with daily bars is exact.
    """
    return [_price((start + timedelta(days=i)).isoformat(), close, volume) for i in range(n)]


# A history long enough that momentum/low_vol/reversal all compute (so the ticker
# survives and we can assert the Part-C factor on the SAME row). 400 daily bars
# ending on asof reaches comfortably past momentum_days(180).
_N = 400
_ASOF = "2020-12-31"
_START = date(2020, 12, 31) - timedelta(days=_N - 1)


# ===========================================================================
# TASK 4 — max_lottery = -max(daily return over last max_days as-of bars)
# ===========================================================================


def test_max_lottery_known_value_single_up_day():
    # Flat history EXCEPT one big +50% up-day inside the max window. The largest
    # daily return in the window is that +0.50, so max_lottery = -0.50.
    bars = _flat_bars(_START, _N, close=100.0)
    # Put the spike 5 days before asof: close jumps 100 -> 150 on that bar, then
    # stays 150 (so there is exactly one +0.5 return and no later moves).
    spike_idx = _N - 6
    for i in range(spike_idx, _N):
        bars[i] = _price(bars[i].time, 150.0)
    bundles = {"LOTTO": SimpleNamespace(prices=bars, metrics_history=[])}

    out = compute_factors(bundles, _ASOF, _config(max_days=21))["LOTTO"]
    assert out["max_lottery"] == -0.5
    # Higher-z-is-better sign: a lottery spike makes the factor NEGATIVE.
    assert out["max_lottery"] < 0
    # Ticker still has its other factors.
    assert "momentum" in out and "low_vol" in out and "reversal" in out


def test_max_lottery_no_lookahead_post_asof_spike_ignored():
    # Identical flat history through asof in both bundles; bundle B adds an enormous
    # up-spike on bars AFTER asof. The post-asof spike must not change max_lottery.
    base = _flat_bars(_START, _N, close=100.0)
    a = {"X": SimpleNamespace(prices=list(base), metrics_history=[])}

    after = date(2020, 12, 31)
    # Huge jumps strictly after asof (would be the max daily return BY FAR if seen).
    spike = [_price((after + timedelta(days=k)).isoformat(), 100.0 * (10**k)) for k in range(1, 6)]
    b = {"X": SimpleNamespace(prices=list(base) + spike, metrics_history=[])}

    cfg = _config(max_days=21)
    fa = compute_factors(a, _ASOF, cfg)["X"]
    fb = compute_factors(b, _ASOF, cfg)["X"]
    assert fa["max_lottery"] == fb["max_lottery"]
    # Flat history → no up-moves at all → max return is 0.0 → factor is exactly 0.0.
    # A leak of the +900% post-asof day would have driven it to -9.0.
    assert fa["max_lottery"] == 0.0


def test_max_lottery_none_when_insufficient_window():
    # max_days clamped so the trailing window yields < 1 return → max_lottery None,
    # but the ticker still computes its other factors from the full history.
    bars = _flat_bars(_START, _N, close=100.0)
    bundles = {"Y": SimpleNamespace(prices=bars, metrics_history=[])}
    out = compute_factors(bundles, _ASOF, _config(max_days=0))["Y"]
    assert out["max_lottery"] is None
    assert out["momentum"] is not None


# ===========================================================================
# TASK 5 — high_52w = close[asof] / max(close over last hi_days as-of bars)
# ===========================================================================


def test_high_52w_at_rolling_high_is_one():
    # Monotonically RISING closes → the last (asof) bar IS the rolling max, so the
    # 52-week-high proximity is exactly 1.0.
    bars = [_price((_START + timedelta(days=i)).isoformat(), 100.0 + i) for i in range(_N)]
    bundles = {"HI": SimpleNamespace(prices=bars, metrics_history=[])}
    out = compute_factors(bundles, _ASOF, _config(hi_days=252))["HI"]
    assert out["high_52w"] == 1.0


def test_high_52w_below_peak_is_known_ratio():
    # A peak of 200 occurs inside the hi_days window, then price falls back to 150 at
    # asof → high_52w = 150 / 200 = 0.75 (strictly between 0 and 1).
    bars = _flat_bars(_START, _N, close=100.0)
    # Peak 10 days before asof, then settle at 150 through asof.
    peak_idx = _N - 11
    bars[peak_idx] = _price(bars[peak_idx].time, 200.0)
    for i in range(peak_idx + 1, _N):
        bars[i] = _price(bars[i].time, 150.0)
    bundles = {"HB": SimpleNamespace(prices=bars, metrics_history=[])}
    out = compute_factors(bundles, _ASOF, _config(hi_days=252))["HB"]
    assert out["high_52w"] == 150.0 / 200.0


def test_high_52w_no_lookahead_post_asof_peak_ignored():
    # Rising history through asof (asof bar is the in-sample max → ratio 1.0). Bundle B
    # adds a massive post-asof peak. A leak would push the rolling max ABOVE the asof
    # close and drive the ratio well below 1.0 — it must stay exactly 1.0.
    base = [_price((_START + timedelta(days=i)).isoformat(), 100.0 + i) for i in range(_N)]
    a = {"X": SimpleNamespace(prices=list(base), metrics_history=[])}

    after = date(2020, 12, 31)
    peak = [_price((after + timedelta(days=k)).isoformat(), 10_000_000.0) for k in range(1, 6)]
    b = {"X": SimpleNamespace(prices=list(base) + peak, metrics_history=[])}

    cfg = _config(hi_days=252)
    fa = compute_factors(a, _ASOF, cfg)["X"]
    fb = compute_factors(b, _ASOF, cfg)["X"]
    assert fa["high_52w"] == fb["high_52w"]
    assert fa["high_52w"] == 1.0


def test_high_52w_none_when_no_bars_in_window():
    # hi_days = 0 → no bars in the rolling-high window → high_52w None, but the ticker
    # still computes its other factors.
    bars = _flat_bars(_START, _N, close=100.0)
    bundles = {"Z": SimpleNamespace(prices=bars, metrics_history=[])}
    out = compute_factors(bundles, _ASOF, _config(hi_days=0))["Z"]
    assert out["high_52w"] is None
    assert out["momentum"] is not None
