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


def _config(*, momentum_days=180, vol_days=30, reversal_days=10, max_days=21, hi_days=252, to_days=21, resid_days=252) -> SimpleNamespace:
    """A minimal stand-in for ``StrategyConfig`` — only ``.lookback`` is read."""
    return SimpleNamespace(
        lookback={
            "momentum_days": momentum_days,
            "vol_days": vol_days,
            "reversal_days": reversal_days,
            "max_days": max_days,
            "hi_days": hi_days,
            "to_days": to_days,
            "resid_days": resid_days,
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
# TASK 8 — gross_prof = gross_margin (gross_profit / revenue) from lagged metrics.
#          A SINGLE homogeneous source (M1 fix): NO line-items asset-scaled path, so
#          the cross-section is never a mix of margin-scaled and asset-scaled ratios.
# ===========================================================================


def test_gross_prof_from_gross_margin():
    # The lagged metrics gross_margin IS the factor: 0.30 → 0.30.
    bundle = _fund_bundle([], metrics=[_gm(_FY, gross_margin=0.30)])
    out = compute_factors({"GP": bundle}, _ASOF, _config())["GP"]
    assert out["gross_prof"] == 0.30
    assert all(k in out for k in _PRICE_KEYS)


def test_gross_prof_ignores_line_items_for_homogeneity():
    # Line items carry gross_profit + total_assets, but with NO metrics gross_margin the
    # factor is None — proving gross_prof uses ONLY the homogeneous gross_margin source
    # and does NOT mix in the asset-scaled line-items ratio (the M1 fix).
    items = [_li(_FY, gross_profit=300.0, total_assets=1000.0)]
    out = compute_factors({"GP": _fund_bundle(items)}, _ASOF, _config())["GP"]
    assert out["gross_prof"] is None
    assert all(k in out for k in _PRICE_KEYS)


def test_gross_prof_no_lookahead_uses_lagged_metric():
    # A high gross_margin dated INSIDE the 60-day lag must be excluded; the older
    # knowable metrics record (0.20) is used, never the leaked 0.99.
    metrics = [
        _gm(_FY_TOO_RECENT, gross_margin=0.99),  # < 60d → not knowable
        _gm(_FY, gross_margin=0.20),  # knowable → used
    ]
    out = compute_factors({"GP": _fund_bundle([], metrics=metrics)}, _ASOF, _config())["GP"]
    assert out["gross_prof"] == 0.20
    assert out["gross_prof"] != 0.99


def test_gross_prof_none_when_no_source():
    # No line-items gross/assets and no gross_margin metric → gross_prof None; the
    # ticker still returns its price factors.
    bundle = _fund_bundle([_li(_FY, total_assets=1000.0)])  # assets but no profit
    out = compute_factors({"GP": bundle}, _ASOF, _config())["GP"]
    assert out["gross_prof"] is None
    assert out["momentum"] is not None


# ===========================================================================
# TASK 9 — asset_growth = -(ta_t / ta_prev - 1)  (Cooper-Gulen-Schill / FF5 CMA)
#          high asset growth → low future return → NEGATIVE sign.
# ===========================================================================


def test_asset_growth_known_value():
    # total_assets 200 now vs 100 prior year → growth +1.0 → asset_growth = -1.0.
    items = [
        _li(_FY, total_assets=200.0),
        _li(_FY_PRIOR, total_assets=100.0),
    ]
    out = compute_factors({"AG": _fund_bundle(items)}, _ASOF, _config())["AG"]
    assert out["asset_growth"] == -1.0
    # Higher-z-is-better: rapid asset growth is PENALISED (negative factor).
    assert out["asset_growth"] < 0
    assert all(k in out for k in _PRICE_KEYS)


def test_asset_growth_shrinking_assets_is_positive():
    # Assets SHRANK (100 now vs 200 prior) → growth -0.5 → asset_growth = +0.5 (good).
    items = [
        _li(_FY, total_assets=100.0),
        _li(_FY_PRIOR, total_assets=200.0),
    ]
    out = compute_factors({"AG": _fund_bundle(items)}, _ASOF, _config())["AG"]
    assert out["asset_growth"] == 0.5


def test_asset_growth_no_lookahead_uses_lagged_pair():
    # A record INSIDE the 60-day lag must NOT serve as ta_t. The knowable pair
    # (ta_t=200 @ _FY, ta_prev=100 @ _FY_PRIOR) → -1.0. A leak of the too-recent
    # 1000 as ta_t would give -(1000/200 - 1) = -4.0.
    items = [
        _li(_FY_TOO_RECENT, total_assets=1000.0),  # < 60d → not knowable
        _li(_FY, total_assets=200.0),  # latest knowable → ta_t
        _li(_FY_PRIOR, total_assets=100.0),  # prior fiscal year → ta_prev
    ]
    out = compute_factors({"AG": _fund_bundle(items)}, _ASOF, _config())["AG"]
    assert out["asset_growth"] == -1.0
    assert out["asset_growth"] != -4.0


def test_asset_growth_none_when_no_prior_year():
    # Only one knowable record → no prior year to compare → asset_growth None, but the
    # ticker keeps its price factors.
    items = [_li(_FY, total_assets=200.0)]
    out = compute_factors({"AG": _fund_bundle(items)}, _ASOF, _config())["AG"]
    assert out["asset_growth"] is None
    assert out["momentum"] is not None


def test_asset_growth_none_when_prior_assets_zero():
    # Prior-year total_assets == 0 → division guarded → asset_growth None; price
    # factors survive.
    items = [
        _li(_FY, total_assets=200.0),
        _li(_FY_PRIOR, total_assets=0.0),
    ]
    out = compute_factors({"AG": _fund_bundle(items)}, _ASOF, _config())["AG"]
    assert out["asset_growth"] is None
    assert out["momentum"] is not None


# ===========================================================================
# TASK 10 — quality = eps / book_value_per_share  (= NI/equity = ROE)
# ===========================================================================


def test_quality_known_roe():
    # EPS = 5, BVPS = 25 → quality = EPS/BVPS = NI/equity = ROE = 0.2.
    items = [_li(_FY, earnings_per_share=5.0, book_value_per_share=25.0)]
    out = compute_factors({"Q": _fund_bundle(items)}, _ASOF, _config())["Q"]
    assert out["quality"] == 0.2
    # Higher-z-is-better: positive ROE is a POSITIVE factor.
    assert out["quality"] > 0
    assert all(k in out for k in _PRICE_KEYS)


def test_quality_negative_eps_yields_negative_roe():
    # Unlike value (E/P, which requires EPS>0), quality (ROE) admits a loss: EPS=-5,
    # BVPS=25 → quality = -0.2 (negative ROE is still a meaningful quality signal).
    items = [_li(_FY, earnings_per_share=-5.0, book_value_per_share=25.0)]
    out = compute_factors({"Q": _fund_bundle(items)}, _ASOF, _config())["Q"]
    assert out["quality"] == -0.2
    # value, by contrast, is None on a loss (EPS <= 0).
    assert out["value"] is None


def test_quality_no_lookahead_uses_lagged_line_item():
    # A high-ROE record dated INSIDE the 60-day lag must be excluded; the older
    # knowable record (ROE=0.2) is used, never the leaked 5.0.
    items = [
        _li(_FY_TOO_RECENT, earnings_per_share=50.0, book_value_per_share=10.0),  # < 60d → not knowable
        _li(_FY, earnings_per_share=5.0, book_value_per_share=25.0),  # knowable → used
    ]
    out = compute_factors({"Q": _fund_bundle(items)}, _ASOF, _config())["Q"]
    assert out["quality"] == 0.2
    assert out["quality"] != 5.0


def test_quality_none_when_bvps_not_positive():
    # BVPS == 0 → ROE not computable (division guarded) → quality None; price factors
    # survive.
    items = [_li(_FY, earnings_per_share=5.0, book_value_per_share=0.0)]
    out = compute_factors({"Q": _fund_bundle(items)}, _ASOF, _config())["Q"]
    assert out["quality"] is None
    assert out["momentum"] is not None


def test_quality_none_when_no_line_item():
    # No knowable line item → quality None; the ticker keeps all its price factors.
    out = compute_factors({"Q": _fund_bundle([])}, _ASOF, _config())["Q"]
    assert out["quality"] is None
    assert all(k in out for k in _PRICE_KEYS)


def test_all_eleven_factor_keys_present():
    # A fully-populated bundle emits every one of the 11 registered factor keys (the
    # 3 price + 3 Part-3a price/vol + 4 fundamentals + cross-sectional resid_mom).
    items = [
        _li(_FY, earnings_per_share=5.0, book_value_per_share=25.0, total_assets=1000.0),
        _li(_FY_PRIOR, total_assets=800.0),
    ]
    # gross_prof now reads the homogeneous gross_margin off metrics (M1 fix), not the
    # line-items asset-scaled ratio.
    out = compute_factors({"ALL": _fund_bundle(items, metrics=[_gm(_FY, gross_margin=0.3)])}, _ASOF, _config())["ALL"]
    expected = {
        "momentum",
        "low_vol",
        "reversal",
        "value",
        "quality",
        "max_lottery",
        "high_52w",
        "turnover",
        "resid_mom",
        "gross_prof",
        "asset_growth",
    }
    assert set(out) == expected
    # Every emitted fundamental factor computed (none degraded to None on this bundle).
    assert out["value"] == 0.05
    assert out["quality"] == 0.2
    assert out["gross_prof"] == 0.3
    assert out["asset_growth"] == -(1000.0 / 800.0 - 1.0)
    # resid_mom is cross-sectional: a single-ticker universe (market == the stock)
    # has zero residual variance, so it degrades to None here (still a present key).
    assert out["resid_mom"] is None


# ===========================================================================
# TASK 11 — resid_mom (residual / idiosyncratic momentum), CROSS-SECTIONAL.
#
# Computed in compute_factors (not _compute_one) because it needs the MARKET
# return series = the equal-weight cross-sectional MEAN daily return across ALL
# tickers in the output. For each ticker a 1-factor OLS of its daily returns y on
# the market x yields slope b (market beta) and intercept a; resid_mom = a, the
# average market-residualized (idiosyncratic) return — the part of the stock's
# drift NOT explained by co-movement with the market. Higher = better (no flip).
#
# Built from explicit daily-return sequences so the market (the mean of those
# sequences) is known exactly. Closes are the cumulative product of (1 + r).
# ===========================================================================


def _bars_from_returns(returns: list[float], *, start: date = _START, close0: float = 100.0) -> list[SimpleNamespace]:
    """Daily bars whose consecutive close ratios reproduce ``returns`` exactly.

    The first bar sits at ``start`` with close ``close0``; bar ``i+1`` has close
    ``close[i] * (1 + returns[i])``. So ``len(returns) + 1`` bars yield exactly the
    given daily-return series — letting a test pin the cross-sectional market.
    """
    closes = [close0]
    for r in returns:
        closes.append(closes[-1] * (1.0 + r))
    return [_price((start + timedelta(days=i)).isoformat(), c) for i, c in enumerate(closes)]


# A market return series with real variance (so Σ(x-x̄)² is well above any floor)
# and a near-zero mean (so the no-intercept-vs-intercept distinction is sharp and
# the intercept reads cleanly). Long enough that all price factors also compute.
_MKT_RETS = [0.02 if i % 2 == 0 else -0.02 for i in range(_N - 1)]


def _market_peers(n: int) -> dict[str, SimpleNamespace]:
    """``n`` tickers that ALL track ``_MKT_RETS`` exactly — a broad pure-market crowd.

    Adding many such peers makes the equal-weight cross-sectional market ≈ ``_MKT_RETS``
    even when one extra ticker carries an idiosyncratic drift, so that ticker's OLS
    intercept recovers (approximately) its FULL injected drift rather than a fraction of
    it diluted by its own weight in a tiny universe.
    """
    return {f"MKT{i}": SimpleNamespace(prices=_bars_from_returns(list(_MKT_RETS)), metrics_history=[]) for i in range(n)}


def test_resid_mom_zero_when_stock_moves_with_market():
    # Two tickers with the IDENTICAL return series → the cross-sectional market mean
    # equals each stock's returns, so each stock moves EXACTLY with the market. The
    # 1-factor fit is y = 0 + 1*x (zero idiosyncratic drift) → resid_mom ≈ 0.
    bars_a = _bars_from_returns(_MKT_RETS)
    bars_b = _bars_from_returns(_MKT_RETS)
    bundles = {
        "A": SimpleNamespace(prices=bars_a, metrics_history=[]),
        "B": SimpleNamespace(prices=bars_b, metrics_history=[]),
    }
    out = compute_factors(bundles, _ASOF, _config())
    assert abs(out["A"]["resid_mom"]) < 1e-9
    assert abs(out["B"]["resid_mom"]) < 1e-9


def test_resid_mom_positive_when_stock_has_idiosyncratic_drift():
    # Ticker A = market + a constant idiosyncratic drift on EVERY day, set against a
    # broad crowd of pure-market peers (so the equal-weight market ≈ _MKT_RETS and A's
    # own weight in it is negligible). A's extra per-day drift is the part the market
    # cannot explain, so its residual (idiosyncratic) momentum is positive and recovers
    # ≈ the full injected drift, while the pure-market peers sit at ≈ 0. Higher-z-is-
    # better: idiosyncratic up-drift scores high.
    drift = 0.003
    a_rets = [r + drift for r in _MKT_RETS]
    bundles = {"A": SimpleNamespace(prices=_bars_from_returns(a_rets), metrics_history=[])}
    bundles.update(_market_peers(29))  # 30 tickers total → market is ~pure _MKT_RETS
    out = compute_factors(bundles, _ASOF, _config())
    # A's idiosyncratic drift is positive and ≈ the injected constant; the pure-market
    # peers are essentially zero (and strictly below A).
    assert out["A"]["resid_mom"] > 0
    assert abs(out["A"]["resid_mom"] - drift) < 1e-3
    assert out["A"]["resid_mom"] > out["MKT0"]["resid_mom"]
    assert abs(out["MKT0"]["resid_mom"]) < 1e-3


def test_resid_mom_no_lookahead_post_asof_move_ignored():
    # Identical history THROUGH asof in both runs; run B appends an enormous post-asof
    # move to one ticker. Returns enter resid_mom only from bars <= asof, so the spike
    # is invisible and resid_mom is byte-identical across the two runs.
    a_rets = [r + 0.003 for r in _MKT_RETS]
    b_rets = list(_MKT_RETS)
    base_a = _bars_from_returns(a_rets)
    base_b = _bars_from_returns(b_rets)

    after = date(2020, 12, 31)
    spike = [_price((after + timedelta(days=k)).isoformat(), 100.0 * (10**k)) for k in range(1, 6)]

    clean = {
        "A": SimpleNamespace(prices=list(base_a), metrics_history=[]),
        "B": SimpleNamespace(prices=list(base_b), metrics_history=[]),
    }
    leaked = {
        "A": SimpleNamespace(prices=list(base_a) + spike, metrics_history=[]),
        "B": SimpleNamespace(prices=list(base_b), metrics_history=[]),
    }
    cfg = _config()
    fc = compute_factors(clean, _ASOF, cfg)
    fl = compute_factors(leaked, _ASOF, cfg)
    assert fc["A"]["resid_mom"] == fl["A"]["resid_mom"]
    assert fc["B"]["resid_mom"] == fl["B"]["resid_mom"]


def test_resid_mom_cache_not_polluted_yet_recomputed():
    # resid_mom is cross-sectional and UNCACHED: it must be recomputed every call and
    # must NEVER be written into the Part-B per-ticker cache (which stores only the 10
    # _compute_one factors, keyed by ticker/asof/lookbacks). Running twice with the
    # same cache must (a) leave every cached dict free of "resid_mom", yet (b) still
    # surface a correct resid_mom in the OUTPUT, and (c) serve the 10 cached factors
    # byte-identically on the second (pure-hit) call.
    drift = 0.003
    a_rets = [r + drift for r in _MKT_RETS]
    bundles = {"A": SimpleNamespace(prices=_bars_from_returns(a_rets), metrics_history=[])}
    bundles.update(_market_peers(29))  # broad market so A's intercept ≈ the full drift
    cfg = _config()
    cache: dict = {}

    out1 = compute_factors(bundles, _ASOF, cfg, cache=cache)
    out2 = compute_factors(bundles, _ASOF, cfg, cache=cache)

    # (a) The cache holds the raw _compute_one dicts and is NOT polluted with resid_mom.
    assert cache, "cache should have been populated"
    for cached_factors in cache.values():
        assert "resid_mom" not in cached_factors

    # (b) The OUTPUT does carry a correct (positive, ~drift) resid_mom for A.
    assert out1["A"]["resid_mom"] > 0
    assert abs(out1["A"]["resid_mom"] - drift) < 1e-3
    # The output dict is a COPY — its resid_mom did not leak back into the cache.
    assert out1["A"]["resid_mom"] == out2["A"]["resid_mom"]

    # (c) The 10 cached factors are byte-identical across the two calls (a pure hit),
    # i.e. only resid_mom is recomputed/re-attached, never the underlying panel.
    for ticker in bundles:
        cached_only = {k: v for k, v in out1[ticker].items() if k != "resid_mom"}
        cached_only2 = {k: v for k, v in out2[ticker].items() if k != "resid_mom"}
        assert cached_only == cached_only2


def test_resid_mom_none_for_single_ticker_universe():
    # Degenerate cross-section: ONE ticker → the market mean IS that ticker's return
    # series → stock == market → zero residual variance / a perfectly determined fit
    # with no idiosyncratic component. resid_mom degrades to None with NO exception.
    bundles = {"SOLO": SimpleNamespace(prices=_bars_from_returns(_MKT_RETS), metrics_history=[])}
    out = compute_factors(bundles, _ASOF, _config())
    assert out["SOLO"]["resid_mom"] is None
    # The single ticker still computes all its other factors.
    assert out["SOLO"]["momentum"] is not None


# ===========================================================================
# TASK 12 — final integration smoke. Exercises the REAL baseline config
# (strategy_skill/skill_config.yaml) end-to-end through compute_factors AND
# generate_holdings, proving (a) a fully-populated bundle emits all 11 factors,
# and (b) the six NEW Part-C factors actually DRIVE selection — up-weighting a
# new factor (value) yields a DIFFERENT book than the balanced baseline, so they
# are not inert/neutral.
# ===========================================================================

import os

from v2.self_evolve.config import FACTOR_KEYS, apply_delta, load_config, validate
from v2.self_evolve.strategy_gen import generate_holdings

_SKILL_CONFIG = os.path.join(os.path.dirname(__file__), "..", "..", "strategy_skill", "skill_config.yaml")


def test_baseline_config_loads_validated_with_eleven_normalized_weights():
    # The rebalanced 11-factor baseline still passes the protocol gate: exactly the
    # 11 canonical keys, weights normalized to 1.0, every adjustable path in range.
    cfg = load_config(_SKILL_CONFIG)
    validate(cfg)  # no raise
    assert set(cfg.factor_weights) == set(FACTOR_KEYS)
    assert sum(cfg.factor_weights.values()) == __import__("pytest").approx(1.0)
    # It is genuinely balanced — no factor sits at the old token 0.05 seed, and
    # momentum still leads (price-led kernel preserved).
    assert min(cfg.factor_weights.values()) > 0.05
    assert cfg.factor_weights["momentum"] == max(cfg.factor_weights.values())


def test_compute_factors_emits_all_eleven_keys_on_real_config():
    # A healthy multi-ticker bundle WITH line_items_history + prices, run through the
    # REAL baseline config, emits every one of the 11 factor keys for each ticker;
    # the data-supported ones are non-None (resid_mom is real here because the
    # cross-section has >1 ticker with idiosyncratic drift).
    cfg = load_config(_SKILL_CONFIG)
    bundles = _smoke_universe()
    rows = compute_factors(bundles, _ASOF, cfg)
    assert set(rows) == set(bundles)  # every ticker survived (long, healthy history)
    for ticker, row in rows.items():
        assert set(row) == set(FACTOR_KEYS), f"{ticker} missing keys: {set(FACTOR_KEYS) - set(row)}"
        # The price/volume factors + the four fundamentals are all backed by data,
        # so none degrades to None on this fully-populated bundle.
        for k in FACTOR_KEYS:
            if k == "resid_mom":
                continue  # cross-sectional; asserted separately below
            assert row[k] is not None, f"{ticker}.{k} unexpectedly None"
    # resid_mom is real (non-None) for at least one name — the multi-ticker
    # cross-section gives the market series a genuine residual to fit against.
    assert any(rows[t]["resid_mom"] is not None for t in rows)


def test_upweighting_new_factor_changes_holdings():
    # Proof the NEW factors are live, not neutral: take the balanced baseline book,
    # then apply a delta that makes a NEW factor (value) dominate the blend. Because
    # the synthetic universe's value ranking is ANTI-correlated with its price-factor
    # ranking, a value-dominated composite selects/weights a DIFFERENT set of names —
    # which can only happen if `value` actually feeds the composite.
    base_cfg = load_config(_SKILL_CONFIG)
    # Make selection sensitive: drop the liquidity filter (all 40 names survive) and set
    # top_n (20, the ADJUSTABLE floor) WELL below 40, so which names are held is decided
    # purely by the composite ordering — a value tilt that reorders the composite must
    # change the held SET.
    base_cfg = apply_delta(
        base_cfg,
        {"top_n": 20, "liquidity_pct.advol_pct": 0.0, "liquidity_pct.mktcap_pct": 0.0},
    )

    bundles = _smoke_universe()
    baseline_book = generate_holdings(bundles, _ASOF, base_cfg)
    assert baseline_book, "baseline produced an empty book"
    # Long-only book: positive weights summing to ~1.0.
    assert all(w > 0 for w in baseline_book.values())
    assert sum(baseline_book.values()) == __import__("pytest").approx(1.0)

    # Up-weight the NEW `value` factor to dominate (re-normalized into the blend).
    tilted_cfg = apply_delta(base_cfg, {"factor_weights.value": 1.0})
    tilted_book = generate_holdings(bundles, _ASOF, tilted_cfg)
    assert tilted_book, "value-tilted config produced an empty book"
    assert all(w > 0 for w in tilted_book.values())
    assert sum(tilted_book.values()) == __import__("pytest").approx(1.0)

    # The two books DIFFER — different selected names and/or different weights. If
    # `value` were neutral (z=0 always, as before Part C) the composites would be
    # identical and so would the books.
    assert tilted_book != baseline_book
    # Concretely, the held SET changes.
    assert set(tilted_book) != set(baseline_book)

    # And it changes in the EXPECTED direction: value = EPS/close is largest for the
    # cheapest low-index names, so a value-dominated book is pulled toward them. Its
    # mean held index is strictly below the balanced book's — value really steered it.
    def _mean_idx(book):
        return sum(int(t[1:]) for t in book) / len(book)

    assert _mean_idx(tilted_book) < _mean_idx(baseline_book)


# --- smoke-test universe builder ------------------------------------------


def _smoke_li(report_period: str, **fields) -> SimpleNamespace:
    """A line-item record for the smoke universe (mirrors ``_li``)."""
    return SimpleNamespace(report_period=report_period, **fields)


def _smoke_universe() -> dict[str, SimpleNamespace]:
    """A 40-ticker bundle with prices + line_items_history, engineered so the
    fundamental `value` (E/P) ranking is the REVERSE of the price-momentum ranking,
    with the volatility confound held FLAT so the contrast is clean.

    Every ticker shares the SAME volatile market path (``_MKT_RETS``, alternating
    ±2%) plus a per-ticker CONSTANT daily drift ``0.0001*i``. So:

    * ``low_vol`` is ~identical across tickers (same ±2% swings) → it z-scores to ≈0
      and does NOT differentiate — removing the slope/vol confound a simple ramp has;
    * ``momentum`` (and ``resid_mom``) rise monotonically with ``i`` (more drift =
      stronger trend) → the price block favours HIGH-``i`` names;
    * a fixed EPS over a close that compounds faster for high-``i`` makes
      ``value = EPS/close`` LARGER for the cheaper LOW-``i`` names → value favours
      LOW-``i``, the OPPOSITE direction.

    So the balanced (price-led) book and a value-dominated book pull toward opposite
    ends of the universe and must hold DIFFERENT names — which is only possible if
    `value` actually drives the composite. Healthy ``_N``-bar histories mean every
    ticker survives the price-factor gates.
    """
    n = 40
    bundles: dict[str, SimpleNamespace] = {}
    for i in range(n):
        drift = 0.0001 * i  # constant per-day idiosyncratic drift; vol stays ~flat
        a_rets = [r + drift for r in _MKT_RETS]
        prices = _bars_from_returns(a_rets)  # close compounds faster for higher i
        items = [
            _smoke_li(_FY, earnings_per_share=4.0, book_value_per_share=20.0, total_assets=1000.0 + 10.0 * i),
            _smoke_li(_FY_PRIOR, total_assets=900.0 + 10.0 * i),
        ]
        # gross_prof reads the homogeneous gross_margin off metrics (M1 fix); vary it
        # slightly per name so it is non-degenerate (and non-None) across the cross-section.
        metrics = [SimpleNamespace(report_period=_FY, gross_margin=0.20 + 0.001 * i)]
        bundles[f"S{i:02d}"] = SimpleNamespace(prices=prices, line_items_history=items, metrics_history=metrics)
    return bundles
