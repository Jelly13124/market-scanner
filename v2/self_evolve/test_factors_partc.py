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


# ===========================================================================
# TASK 6 — turnover = -(mean(vol last to_days) / mean(vol full as-of series))
# ===========================================================================


def test_turnover_constant_volume_is_minus_one():
    # Constant volume everywhere → recent mean == full mean → ratio 1.0 → turnover -1.0.
    bars = _flat_bars(_START, _N, close=100.0, volume=500_000.0)
    bundles = {"T": SimpleNamespace(prices=bars, metrics_history=[])}
    out = compute_factors(bundles, _ASOF, _config(to_days=21))["T"]
    assert out["turnover"] == -1.0


def test_turnover_rising_recent_volume_is_more_negative():
    # Baseline volume 100 on the full history; the last `to_days` bars carry a much
    # higher volume → recent mean >> full mean → turnover strictly below -1.0.
    to_days = 10
    bars = _flat_bars(_START, _N, close=100.0, volume=100.0)
    for i in range(_N - to_days, _N):
        bars[i] = _price(bars[i].time, 100.0, 1_000.0)
    bundles = {"TR": SimpleNamespace(prices=bars, metrics_history=[])}
    out = compute_factors(bundles, _ASOF, _config(to_days=to_days))["TR"]
    # Elevated recent volume is PENALISED (more negative than the flat -1.0 baseline).
    assert out["turnover"] < -1.0


def test_turnover_known_value_two_level_volume():
    # Crafted exact value. Full series: N bars. The last `to_days` bars have volume
    # HI, the rest have volume LO. recent_mean = HI; full_mean = (LO*(N-to)+HI*to)/N.
    to_days = 10
    lo, hi = 200.0, 800.0
    bars = _flat_bars(_START, _N, close=100.0, volume=lo)
    for i in range(_N - to_days, _N):
        bars[i] = _price(bars[i].time, 100.0, hi)
    bundles = {"TK": SimpleNamespace(prices=bars, metrics_history=[])}
    out = compute_factors(bundles, _ASOF, _config(to_days=to_days))["TK"]

    recent_mean = hi
    full_mean = (lo * (_N - to_days) + hi * to_days) / _N
    expected = -(recent_mean / full_mean)
    assert abs(out["turnover"] - expected) < 1e-9


def test_turnover_no_lookahead_post_asof_volume_ignored():
    # Identical volume history through asof; bundle B adds an enormous post-asof
    # volume spike. The spike sits after asof → must not change turnover at all.
    base = _flat_bars(_START, _N, close=100.0, volume=300.0)
    a = {"X": SimpleNamespace(prices=list(base), metrics_history=[])}

    after = date(2020, 12, 31)
    spike = [_price((after + timedelta(days=k)).isoformat(), 100.0, 1_000_000_000.0) for k in range(1, 6)]
    b = {"X": SimpleNamespace(prices=list(base) + spike, metrics_history=[])}

    cfg = _config(to_days=21)
    fa = compute_factors(a, _ASOF, cfg)["X"]
    fb = compute_factors(b, _ASOF, cfg)["X"]
    assert fa["turnover"] == fb["turnover"]
    # Flat volume through asof → recent mean == full mean → exactly -1.0. A leak of the
    # 1e9 post-asof volume into either mean would have moved this far from -1.0.
    assert fa["turnover"] == -1.0


def test_turnover_none_when_no_volume_attr():
    # Bars expose NO .volume attribute → turnover cannot be computed → None, but the
    # ticker still returns its price factors (momentum/low_vol/reversal/high_52w).
    bars = [_no_vol_price((_START + timedelta(days=i)).isoformat(), 100.0 + (i % 5)) for i in range(_N)]
    bundles = {"NV": SimpleNamespace(prices=bars, metrics_history=[])}
    out = compute_factors(bundles, _ASOF, _config(to_days=21))["NV"]
    assert out["turnover"] is None
    # The ticker survived with its other factors.
    assert out["momentum"] is not None
    assert out["low_vol"] is not None


def test_turnover_none_when_to_days_zero():
    # to_days = 0 → no recent window → turnover None; ticker keeps its other factors.
    bars = _flat_bars(_START, _N, close=100.0, volume=500_000.0)
    bundles = {"TZ": SimpleNamespace(prices=bars, metrics_history=[])}
    out = compute_factors(bundles, _ASOF, _config(to_days=0))["TZ"]
    assert out["turnover"] is None
    assert out["momentum"] is not None


# ===========================================================================
# Fundamental-factor test infrastructure (Tasks 7-10)
# ===========================================================================
#
# The four fundamental factors (value / gross_prof / asset_growth / quality) are
# computed from raw line items on ``bundle.line_items_history`` — newest record with
# ``report_period <= asof - 60d`` (plus the prior fiscal year for asset_growth). The
# same hard no-lookahead lag the price factors use, applied to statements.
#
# A line-item record is a ``SimpleNamespace`` mirroring the dynamic-attr ``LineItem``:
# ``report_period`` + any of ``total_assets / earnings_per_share /
# book_value_per_share / revenue / cost_of_revenue / gross_profit / net_income``.
# A ``StrategyConfig``-shaped metrics record (``report_period`` + ``gross_margin``)
# feeds the gross_prof fallback.
#
# All fundamental bundles reuse ``_flat_bars`` so the price factors survive (the
# ticker is never dropped) and the as-of close is exactly 100.0 — making E/P and the
# gross/asset ratios pin to round numbers.

# A fiscal period comfortably OUTSIDE the 60-day lag before asof (2020-12-31) → the
# record is knowable as-of and wins ``_latest_lagged_line_item``.
_FY = "2020-06-30"
#: The prior fiscal year, for the asset-growth YoY comparison.
_FY_PRIOR = "2019-06-30"
#: A period INSIDE the 60-day lag window before asof — NOT yet knowable as-of.
_FY_TOO_RECENT = "2020-12-15"


def _li(report_period: str, **fields) -> SimpleNamespace:
    """A line-item record: ``report_period`` + dynamic statement fields.

    Mirrors the dynamic-attr ``LineItem`` the enrich attaches; ``_compute_one`` reads
    each field via ``getattr(rec, name, None)``, so only the supplied fields exist.
    """
    return SimpleNamespace(report_period=report_period, **fields)


def _gm(report_period: str, gross_margin: float) -> SimpleNamespace:
    """A metrics record exposing only ``gross_margin`` (the gross_prof fallback source)."""
    return SimpleNamespace(report_period=report_period, gross_margin=gross_margin)


def _fund_bundle(line_items, *, metrics=None, close: float = 100.0) -> SimpleNamespace:
    """A bundle whose price history survives, carrying synthetic fundamentals.

    ``_flat_bars`` gives a long flat history (as-of close == ``close``) so all price
    factors compute; ``line_items_history`` / ``metrics_history`` carry the synthetic
    fundamentals under test.
    """
    return SimpleNamespace(
        prices=_flat_bars(_START, _N, close=close),
        line_items_history=list(line_items),
        metrics_history=list(metrics or []),
    )


_PRICE_KEYS = ("momentum", "low_vol", "reversal", "max_lottery", "high_52w", "turnover")


# ===========================================================================
# TASK 7 — value = eps / close[asof]  (earnings yield; cheap stock → high z)
# ===========================================================================


def test_value_known_earnings_yield():
    # EPS = 5 on the lagged line item, as-of close = 100 → E/P = 0.05.
    bundles = {"V": _fund_bundle([_li(_FY, earnings_per_share=5.0)], close=100.0)}
    out = compute_factors(bundles, _ASOF, _config())["V"]
    assert out["value"] == 0.05
    # Higher-z-is-better: a positive earnings yield is a POSITIVE factor.
    assert out["value"] > 0
    # The ticker keeps all of its price factors.
    assert all(k in out for k in _PRICE_KEYS)


def test_value_no_lookahead_uses_lagged_line_item():
    # A high-EPS record dated INSIDE the 60-day lag before asof must be excluded; the
    # older knowable record (EPS=2) is used → value = 0.02, never 0.99.
    items = [
        _li(_FY_TOO_RECENT, earnings_per_share=99.0),  # < 60d old → not knowable
        _li(_FY, earnings_per_share=2.0),  # knowable → used
    ]
    out = compute_factors({"V": _fund_bundle(items, close=100.0)}, _ASOF, _config())["V"]
    assert out["value"] == 0.02
    assert out["value"] != 0.99


def test_value_none_when_eps_not_positive():
    # Loss-making (EPS <= 0) → earnings yield not meaningful → value None, but the
    # ticker still returns its price factors.
    bundles = {"V": _fund_bundle([_li(_FY, earnings_per_share=-3.0)], close=100.0)}
    out = compute_factors(bundles, _ASOF, _config())["V"]
    assert out["value"] is None
    assert out["momentum"] is not None


def test_value_none_when_no_line_item():
    # No knowable line item at all → value None; price factors survive.
    bundles = {"V": _fund_bundle([], close=100.0)}
    out = compute_factors(bundles, _ASOF, _config())["V"]
    assert out["value"] is None
    assert all(k in out for k in _PRICE_KEYS)


# ===========================================================================
# TASK 8 — gross_prof = gross_profit / total_assets  (Novy-Marx profitability)
#          fallback: metrics gross_margin when no line-items gross profit/assets.
# ===========================================================================


def test_gross_prof_known_value_from_gross_profit():
    # gross_profit = 300, total_assets = 1000 → gross_prof = 0.3.
    items = [_li(_FY, gross_profit=300.0, total_assets=1000.0)]
    out = compute_factors({"GP": _fund_bundle(items)}, _ASOF, _config())["GP"]
    assert out["gross_prof"] == 0.3
    assert all(k in out for k in _PRICE_KEYS)


def test_gross_prof_derived_from_revenue_minus_cogs():
    # No gross_profit field → derive gp = revenue - cost_of_revenue = 1000 - 600 = 400,
    # over total_assets = 800 → 0.5.
    items = [_li(_FY, revenue=1000.0, cost_of_revenue=600.0, total_assets=800.0)]
    out = compute_factors({"GP": _fund_bundle(items)}, _ASOF, _config())["GP"]
    assert out["gross_prof"] == 400.0 / 800.0


def test_gross_prof_no_lookahead_uses_lagged_line_item():
    # A huge-profitability record dated INSIDE the 60-day lag must be excluded; the
    # older knowable record (gp/assets = 0.2) is used, never the leaked 9.0.
    items = [
        _li(_FY_TOO_RECENT, gross_profit=9000.0, total_assets=1000.0),  # < 60d → not knowable
        _li(_FY, gross_profit=200.0, total_assets=1000.0),  # knowable → used
    ]
    out = compute_factors({"GP": _fund_bundle(items)}, _ASOF, _config())["GP"]
    assert out["gross_prof"] == 0.2
    assert out["gross_prof"] != 9.0


def test_gross_prof_fallback_to_gross_margin():
    # No line-items gross profit / assets at all, but the lagged metrics record carries
    # gross_margin → the factor falls back to that margin directly.
    bundle = _fund_bundle([], metrics=[_gm(_FY, gross_margin=0.42)])
    out = compute_factors({"GP": bundle}, _ASOF, _config())["GP"]
    assert out["gross_prof"] == 0.42


def test_gross_prof_fallback_when_line_item_lacks_assets():
    # A line item exists with gross_profit but NO total_assets → the GP/assets ratio is
    # not computable, so the factor falls back to the metrics gross_margin.
    items = [_li(_FY, gross_profit=300.0)]  # no total_assets
    bundle = _fund_bundle(items, metrics=[_gm(_FY, gross_margin=0.33)])
    out = compute_factors({"GP": bundle}, _ASOF, _config())["GP"]
    assert out["gross_prof"] == 0.33


def test_gross_prof_none_when_no_source():
    # No line-items gross/assets and no gross_margin metric → gross_prof None; the
    # ticker still returns its price factors.
    bundle = _fund_bundle([_li(_FY, total_assets=1000.0)])  # assets but no profit
    out = compute_factors({"GP": bundle}, _ASOF, _config())["GP"]
    assert out["gross_prof"] is None
    assert out["momentum"] is not None
