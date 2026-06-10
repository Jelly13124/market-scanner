"""Offline tests for no-lookahead factor computation (Task 3).

No-lookahead is the load-bearing discipline here: factors at ``asof`` may read ONLY
prices dated ``<= asof`` and fundamentals with ``report_period <= asof - 60d``. These
tests pin the factor signs/formulas, prove that bars AFTER ``asof`` are invisible, and
prove the 60-day fundamental availability lag is honoured.

Bundles are synthetic ``SimpleNamespace`` fakes — no network, no data files, no LLM.
The duck-typed shape (``.prices`` with ``.time``/``.close``; ``.metrics_history`` with
``.report_period``/``.earnings_per_share``/``.return_on_equity``/``.price_to_earnings_ratio``)
is exactly what :func:`compute_factors` reads via ``getattr``.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from v2.self_evolve.factors import (
    FUNDAMENTAL_AVAILABILITY_LAG_DAYS,
    MOMENTUM_SKIP_DAYS,
    compute_factors,
)


# ---------------------------------------------------------------------------
# Synthetic-bundle builders
# ---------------------------------------------------------------------------


def _price(d: str, close: float) -> SimpleNamespace:
    return SimpleNamespace(time=d, close=close)


def _metric(report_period: str, *, eps=None, roe=None, pe=None) -> SimpleNamespace:
    return SimpleNamespace(
        report_period=report_period,
        earnings_per_share=eps,
        return_on_equity=roe,
        price_to_earnings_ratio=pe,
    )


def _li(report_period: str, **fields) -> SimpleNamespace:
    """A raw line-item record (``report_period`` + dynamic statement fields).

    ``value`` (E/P) and ``quality`` (ROE) are computed from these line items, not
    from the ratio metrics; ``_compute_one`` reads each field via ``getattr``.
    """
    return SimpleNamespace(report_period=report_period, **fields)


def _daily_series(start: date, n: int, *, start_price: float, step: float) -> list[SimpleNamespace]:
    """``n`` consecutive calendar-day bars from ``start``, close = start_price + i*step.

    Calendar days (not trading days) keep the offset arithmetic in the tests trivial
    to reason about: ``compute_factors`` snaps to the nearest bar at-or-before each
    target date, and with daily bars that bar lands exactly on the target.
    """
    return [_price((start + timedelta(days=i)).isoformat(), start_price + i * step) for i in range(n)]


def _config(*, momentum_days=180, vol_days=30, reversal_days=10) -> SimpleNamespace:
    """A minimal stand-in for ``StrategyConfig`` — only ``.lookback`` is read."""
    return SimpleNamespace(lookback={"momentum_days": momentum_days, "vol_days": vol_days, "reversal_days": reversal_days})


# ---------------------------------------------------------------------------
# 1. Clean upward series → factor signs + momentum offsets
# ---------------------------------------------------------------------------


def test_upward_series_factor_signs_and_momentum_offsets():
    asof = "2020-12-31"
    # 400 daily bars ending exactly on asof, strictly increasing close.
    start = date(2020, 12, 31) - timedelta(days=399)
    bars = _daily_series(start, 400, start_price=100.0, step=0.5)
    bundles = {"UP": SimpleNamespace(prices=bars, metrics_history=[])}

    cfg = _config(momentum_days=180, vol_days=30, reversal_days=10)
    out = compute_factors(bundles, asof, cfg)

    assert set(out) == {"UP"}
    f = out["UP"]

    # Strictly increasing prices → positive medium-term momentum, negative reversal
    # (recent run-up mean-reverts down), negative low_vol (= -stdev, stdev > 0).
    assert f["momentum"] > 0
    assert f["reversal"] < 0
    assert f["low_vol"] < 0
    # No fundamentals supplied → value/quality absent.
    assert f["value"] is None
    assert f["quality"] is None

    # Momentum must use close[asof - 21d] / close[asof - 180d] - 1 (the 12-1 skip),
    # NOT close[asof]. Recompute the expected value from the known linear series.
    by_date = {p.time: p.close for p in bars}
    recent = by_date[(date(2020, 12, 31) - timedelta(days=MOMENTUM_SKIP_DAYS)).isoformat()]
    far = by_date[(date(2020, 12, 31) - timedelta(days=180)).isoformat()]
    assert f["momentum"] == recent / far - 1.0
    # And it is decidedly NOT the no-skip 12-0 momentum (which would use asof close).
    asof_close = by_date["2020-12-31"]
    assert f["momentum"] != asof_close / far - 1.0


# ---------------------------------------------------------------------------
# 2. NO-LOOKAHEAD: post-asof spike must not change any factor
# ---------------------------------------------------------------------------


def test_post_asof_spike_is_ignored():
    asof = "2020-12-31"
    start = date(2020, 12, 31) - timedelta(days=399)
    # Flat-ish but jittered history through asof (jitter gives a real, nonzero stdev
    # so low_vol is well-defined; the jitter pattern is identical in both bundles).
    base = [_price((start + timedelta(days=i)).isoformat(), 100.0 + (i % 5)) for i in range(400)]

    # Bundle A: history truncated exactly at asof.
    only_past = {"X": SimpleNamespace(prices=list(base), metrics_history=[])}

    # Bundle B: same history PLUS a huge spike on bars strictly AFTER asof.
    after = date(2020, 12, 31)
    spike = [_price((after + timedelta(days=k)).isoformat(), 1_000_000.0 * k) for k in range(1, 31)]
    with_future = {"X": SimpleNamespace(prices=list(base) + spike, metrics_history=[])}

    cfg = _config(momentum_days=180, vol_days=30, reversal_days=10)
    fa = compute_factors(only_past, asof, cfg)["X"]
    fb = compute_factors(with_future, asof, cfg)["X"]

    # The future spike is dated after asof → clamped out → byte-identical factors.
    assert fa == fb
    # Sanity: the spike is genuinely enormous, so the equality is meaningful (a
    # leak would have moved every price factor by orders of magnitude).
    assert max(p.close for p in spike) >= 1_000_000.0


# ---------------------------------------------------------------------------
# 3. Fundamental lag: record inside the 60d window is ignored
# ---------------------------------------------------------------------------


def test_fundamental_60d_lag_excludes_recent_record():
    asof = "2020-12-31"
    start = date(2020, 12, 31) - timedelta(days=399)
    bars = _daily_series(start, 400, start_price=100.0, step=0.5)

    asof_d = date(2020, 12, 31)
    asof_close = bars[-1].close  # linear series: 100 + 399*0.5 = 299.5
    # Inside the lag window (asof - 10d): NOT yet knowable → must be ignored. Its EPS
    # (for value) and ROE (for quality) would both be wildly different if leaked.
    too_recent = _metric((asof_d - timedelta(days=10)).isoformat(), roe=0.99, pe=2.0)
    too_recent_li = _li((asof_d - timedelta(days=10)).isoformat(), earnings_per_share=299.5)
    # Outside the lag window (asof - 90d > 60d lag): knowable → these are used.
    available = _metric((asof_d - timedelta(days=90)).isoformat(), roe=0.15, pe=20.0)
    available_li = _li((asof_d - timedelta(days=90)).isoformat(), earnings_per_share=29.95)

    bundles = {"F": SimpleNamespace(prices=bars, metrics_history=[too_recent, available], line_items_history=[too_recent_li, available_li])}
    out = compute_factors(bundles, asof, _config())["F"]

    # value (E/P) comes from the AVAILABLE line item; quality (ROE) from the available
    # metric — never the too-recent ones.
    assert out["quality"] == 0.15
    assert out["value"] == 29.95 / asof_close  # = 0.1
    # Explicitly NOT the inside-the-window records' values.
    assert out["quality"] != 0.99
    assert out["value"] != 299.5 / asof_close  # the leaked-EPS yield (= 1.0)

    # And if the ONLY records are inside the lag window → value/quality fall back to None.
    only_recent = {"G": SimpleNamespace(prices=bars, metrics_history=[too_recent], line_items_history=[too_recent_li])}
    g = compute_factors(only_recent, asof, _config())["G"]
    assert g["value"] is None
    assert g["quality"] is None
    # The 60d constant is the one the asof client enforces — pin it so a silent
    # change to the lag is caught here.
    assert FUNDAMENTAL_AVAILABILITY_LAG_DAYS == 60


def test_value_requires_positive_eps():
    asof = "2020-12-31"
    start = date(2020, 12, 31) - timedelta(days=399)
    bars = _daily_series(start, 400, start_price=100.0, step=0.5)
    asof_d = date(2020, 12, 31)
    # Negative EPS (loss-making) → earnings yield is not meaningful → value=None,
    # but quality (ROE) still comes through from the lagged metric.
    neg_eps = _li((asof_d - timedelta(days=90)).isoformat(), earnings_per_share=-3.0)
    roe_metric = _metric((asof_d - timedelta(days=90)).isoformat(), roe=0.08)
    bundles = {"N": SimpleNamespace(prices=bars, metrics_history=[roe_metric], line_items_history=[neg_eps])}
    out = compute_factors(bundles, asof, _config())["N"]
    assert out["value"] is None
    assert out["quality"] == 0.08


# ---------------------------------------------------------------------------
# 4. Insufficient history omitted; empty bundles → {}
# ---------------------------------------------------------------------------


def test_insufficient_history_is_omitted():
    asof = "2020-12-31"
    # Only 3 bars but the lookback windows reach back ~180 calendar days, so the far
    # momentum/reversal anchors have no bar at-or-before them → ticker omitted.
    short = {"SHORT": SimpleNamespace(prices=_daily_series(date(2020, 12, 29), 3, start_price=10.0, step=1.0), metrics_history=[])}
    out = compute_factors(short, asof, _config(momentum_days=180, vol_days=30, reversal_days=10))
    assert out == {}


def test_single_bar_is_omitted():
    asof = "2020-12-31"
    one = {"ONE": SimpleNamespace(prices=[_price("2020-12-31", 50.0)], metrics_history=[])}
    assert compute_factors(one, asof, _config()) == {}


def test_empty_bundles_returns_empty():
    assert compute_factors({}, "2020-12-31", _config()) == {}


def test_no_prices_attr_is_omitted_not_raised():
    # A bundle with empty prices must be skipped silently (defensive contract).
    bundles = {"E": SimpleNamespace(prices=[], metrics_history=[])}
    assert compute_factors(bundles, "2020-12-31", _config()) == {}


def test_unparseable_asof_returns_empty():
    start = date(2020, 12, 31) - timedelta(days=399)
    bars = _daily_series(start, 400, start_price=100.0, step=0.5)
    bundles = {"UP": SimpleNamespace(prices=bars, metrics_history=[])}
    assert compute_factors(bundles, "not-a-date", _config()) == {}


# ---------------------------------------------------------------------------
# 5. Mixed universe: some tickers qualify, some omitted, in one call
# ---------------------------------------------------------------------------


def test_mixed_universe_partitions_correctly():
    asof = "2020-12-31"
    start = date(2020, 12, 31) - timedelta(days=399)
    good_prices = _daily_series(start, 400, start_price=100.0, step=0.5)
    good_close = good_prices[-1].close  # 299.5
    good = SimpleNamespace(
        prices=good_prices,
        metrics_history=[_metric("2020-06-30", roe=0.2)],
        line_items_history=[_li("2020-06-30", earnings_per_share=29.95)],
    )
    bad = SimpleNamespace(prices=_daily_series(date(2020, 12, 29), 3, start_price=10.0, step=1.0), metrics_history=[])
    out = compute_factors({"GOOD": good, "BAD": bad}, asof, _config())

    assert set(out) == {"GOOD"}
    assert out["GOOD"]["quality"] == 0.2
    assert out["GOOD"]["value"] == 29.95 / good_close  # E/P = 0.1
    assert all(k in out["GOOD"] for k in ("momentum", "low_vol", "reversal", "value", "quality"))
