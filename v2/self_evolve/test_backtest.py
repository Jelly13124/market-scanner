"""Offline tests for the per-sample factor backtest (Task 5).

``backtest`` walks a sample's monthly rebalance dates, builds the
``generate_holdings`` book on each, holds to the next rebalance date, and
compounds the per-period portfolio returns into a monthly equity curve that is
fed to :class:`~src.backtesting.metrics.PerformanceMetricsCalculator`. These
tests are pure Python — synthetic ``SimpleNamespace`` bundles spanning a sample
window, no network / data files / LLM.

They pin the load-bearing contract:

* a rising market over the val window → positive ``ann_return``, a real
  ``sharpe``, a near-zero (non-positive) ``max_drawdown`` PERCENT, ``n_rebalances`` > 1;
* a market with a clear mid-period DIP → ``max_drawdown`` is NEGATIVE and a
  PERCENT (``abs < 100`` — pinned against the known drawdown, NOT ×100 twice);
* turnover > 0 when the book changes between rebalances, ~0 when it is identical;
* a too-short window (< 2 rebalances) → a graceful dict (None/0 fields), no crash.

The duck-typed bundle shape (``.prices`` with ``.time`` / ``.close`` / ``.volume``)
is exactly what ``generate_holdings`` reads via ``getattr``.
"""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from v2.self_evolve.backtest import backtest
from v2.self_evolve.config import StrategyConfig


# ---------------------------------------------------------------------------
# Synthetic-bundle builders
# ---------------------------------------------------------------------------


def _price(d: str, close: float, volume: float) -> SimpleNamespace:
    return SimpleNamespace(time=d, close=close, volume=volume)


def _daily_dates(start: date, end: date) -> list[date]:
    """Every calendar day in ``[start, end]`` (daily "trading" calendar)."""
    out: list[date] = []
    d = start
    one = timedelta(days=1)
    while d <= end:
        out.append(d)
        d += one
    return out


def _bundle_from_path(
    days: list[date],
    close_fn,
    *,
    volume: float = 2_000_000.0,
) -> SimpleNamespace:
    """A bundle whose close on day ``i`` is ``close_fn(i)`` over the shared calendar."""
    prices = [_price(d.isoformat(), float(close_fn(i)), volume) for i, d in enumerate(days)]
    return SimpleNamespace(prices=prices, metrics_history=[])


def _config(
    *,
    weights=None,
    top_n=30,
    max_weight=0.10,
    advol_pct=0.0,
    mktcap_pct=0.0,
    momentum_days=120,
    vol_days=20,
    reversal_days=5,
) -> StrategyConfig:
    """A real ``StrategyConfig`` (weights sum-normalized in ``__post_init__``)."""
    if weights is None:
        weights = {"momentum": 0.30, "low_vol": 0.25, "reversal": 0.15, "value": 0.15, "quality": 0.15}
    return StrategyConfig(
        factor_weights=dict(weights),
        lookback={"momentum_days": momentum_days, "vol_days": vol_days, "reversal_days": reversal_days},
        top_n=top_n,
        holding_buffer=5,
        max_weight=max_weight,
        liquidity_pct={"mktcap_pct": mktcap_pct, "advol_pct": advol_pct},
        tilt_strength=0.5,
    )


# The val window is [2022-01-01, 2023-12-31]. We span a year of history BEFORE it
# (so the factor lookbacks have data on the first rebalance) through the end of val.
HIST_START = date(2021, 1, 1)
VAL_END = date(2023, 12, 31)
VAL_DAYS = _daily_dates(HIST_START, VAL_END)

EXPECTED_KEYS = {"sharpe", "ann_return", "ann_vol", "max_drawdown", "turnover", "n_rebalances"}


# ---------------------------------------------------------------------------
# 1. rising market → positive ann_return, real sharpe, ~0 maxDD, n_rebalances>1
# ---------------------------------------------------------------------------


def test_rising_market_positive_return():
    # Five names all ramping steadily upward (different slopes so the book is
    # well-defined and non-degenerate) over the whole history+val window. A
    # monotonically rising market → positive annualized return and essentially no
    # drawdown.
    slopes = {"A": 0.10, "B": 0.09, "C": 0.08, "D": 0.07, "E": 0.06}
    jitter = 0.5  # small wiggle so realized vol (hence the vol-inverse weight) is defined
    bundles = {t: _bundle_from_path(VAL_DAYS, lambda i, s=s: 100.0 + s * i + (i % 5) * jitter) for t, s in slopes.items()}
    cfg = _config(top_n=5, max_weight=0.30)

    res = backtest(bundles, cfg, "val")

    assert set(res) == EXPECTED_KEYS
    assert res["n_rebalances"] > 1
    assert res["ann_return"] is not None and res["ann_return"] > 0.0
    assert res["sharpe"] is not None
    assert res["ann_vol"] is not None and res["ann_vol"] >= 0.0
    # A steadily rising market has at most a tiny drawdown from the small wiggle;
    # crucially it is a PERCENT (|dd| < 100) and non-positive, never ×100 twice.
    assert res["max_drawdown"] is not None
    assert -100.0 < res["max_drawdown"] <= 0.0


# ---------------------------------------------------------------------------
# 2. mid-period DIP → max_drawdown NEGATIVE, a PERCENT, pinned (not ×100 twice)
# ---------------------------------------------------------------------------


def test_midperiod_dip_drawdown_is_a_percent():
    # Build a market that, INSIDE the val window, rises to a clear peak, then drops
    # ~25% across one rebalance period, sits depressed, then recovers. The
    # portfolio (long-only, fully invested, all names sharing the shape) takes the
    # full ~25% drawdown off that peak. We pin that the reported max_drawdown is
    # NEGATIVE and a sane PERCENT (~ -25, well within (-100, 0)) — i.e. the calc's
    # already-×100 value is passed through AS-IS, not multiplied by 100 again
    # (which would give ~ -2500).
    #
    # Phased by CALENDAR DATE (not calendar index) so the peak/dip land on real
    # month-start rebalance dates: the val window starts 2022-01-01, so we ramp up
    # through H1-2022 (peak ~ 2022-07-01), step ~25% lower from 2022-07-01 through
    # year-end, then restore in 2023. A drawdown therefore exists off the H1 peak.
    def shape(iso: str) -> float:
        # iso == "YYYY-MM-DD"; phase on the month.
        peak = 125.0  # level reached by the 2022-07 peak
        if iso < "2022-07-01":
            # Ramp 100 -> ~125 across H1-2022 (≈181 days), flat-ish before val proper.
            day0 = date(2022, 1, 1).toordinal()
            cur = date.fromisoformat(iso).toordinal()
            frac = max(0.0, min(1.0, (cur - day0) / 181.0))
            return 100.0 + (peak - 100.0) * frac
        if iso < "2023-01-01":
            return peak * 0.75  # ~25% drawdown off the peak through H2-2022
        return peak  # recovered back to the peak in 2023

    # All names share the dip SHAPE (so every book takes the drawdown); a tiny
    # per-name constant offset + a small jitter just keep the cross-section
    # non-degenerate so the book is well-formed.
    offsets = {"A": 0.0, "B": 0.2, "C": 0.4, "D": 0.6, "E": 0.8}
    jitter = 0.1
    bundles = {t: _bundle_from_path(VAL_DAYS, lambda i, off=off: shape(VAL_DAYS[i].isoformat()) + off + (i % 5) * jitter) for t, off in offsets.items()}
    cfg = _config(top_n=5, max_weight=0.30)

    res = backtest(bundles, cfg, "val")

    assert res["n_rebalances"] > 1
    assert res["max_drawdown"] is not None
    # NEGATIVE, and a percent in a believable band for a ~25% dip — definitely not
    # the ~ -2500 you'd get from a double ×100.
    assert res["max_drawdown"] < 0.0
    assert -60.0 < res["max_drawdown"] < -5.0


# ---------------------------------------------------------------------------
# 3. turnover: changing book → > 0; identical book → ~0
# ---------------------------------------------------------------------------


def test_turnover_positive_when_holdings_rotate():
    # Two names whose RELATIVE momentum ranking FLIPS halfway through the window:
    # WIN leads early, then LATE overtakes. With top_n=1 the held name rotates from
    # WIN to LATE, so Σ|Δw| jumps to ~2 on the rotation → mean turnover > 0.
    n = len(VAL_DAYS)
    half = n // 2

    def win_path(i: int) -> float:
        # Rises fast early, then flattens.
        return 100.0 + (0.20 * i if i < half else 0.20 * half + 0.01 * (i - half)) + (i % 5) * 0.3

    def late_path(i: int) -> float:
        # Flat early, then rises fast — overtakes WIN's recent momentum after `half`.
        return 100.0 + (0.01 * i if i < half else 0.01 * half + 0.40 * (i - half)) + (i % 5) * 0.3

    bundles = {
        "WIN": _bundle_from_path(VAL_DAYS, win_path),
        "LATE": _bundle_from_path(VAL_DAYS, late_path),
    }
    cfg = _config(
        weights={"momentum": 1.0, "low_vol": 0.0, "reversal": 0.0, "value": 0.0, "quality": 0.0},
        top_n=1,
        max_weight=0.99,
    )

    res = backtest(bundles, cfg, "val")
    assert res["n_rebalances"] > 1
    assert res["turnover"] > 0.0


def test_turnover_zero_when_holdings_identical():
    # A single eligible name → every rebalance holds {THE: 1.0}, so the book never
    # changes → Σ|Δw| == 0 at every rebalance → mean turnover ~ 0.
    bundles = {
        "THE": _bundle_from_path(VAL_DAYS, lambda i: 100.0 + 0.05 * i + (i % 5) * 0.3),
    }
    cfg = _config(top_n=5, max_weight=0.99)

    res = backtest(bundles, cfg, "val")
    assert res["n_rebalances"] > 1
    assert res["turnover"] == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 4. too-few rebalances → graceful dict, no crash
# ---------------------------------------------------------------------------


def test_too_few_rebalances_graceful():
    # A window with only ONE rebalance month (a few days inside Jan-2022) → < 2
    # rebalances → no held period → graceful dict, metric fields None/0, no crash.
    days = _daily_dates(date(2022, 1, 1), date(2022, 1, 10))
    bundles = {t: _bundle_from_path(days, lambda i, s=s: 100.0 + s * i) for t, s in {"A": 0.1, "B": 0.2}.items()}
    res = backtest(bundles, _config(), "val")

    assert set(res) == EXPECTED_KEYS
    assert res["n_rebalances"] <= 1
    assert res["sharpe"] is None
    assert res["ann_return"] is None
    assert res["ann_vol"] is None
    assert res["max_drawdown"] is None
    assert res["turnover"] == 0.0


def test_empty_bundles_graceful():
    res = backtest({}, _config(), "val")
    assert set(res) == EXPECTED_KEYS
    assert res["n_rebalances"] == 0
    assert res["sharpe"] is None
    assert res["turnover"] == 0.0


def test_never_raises_on_garbage_bundle():
    # A bundle missing .prices entirely must be tolerated (defensive contract).
    res = backtest({"BAD": SimpleNamespace(metrics_history=[])}, _config(), "val")
    assert set(res) == EXPECTED_KEYS
    assert res["n_rebalances"] == 0


# ---------------------------------------------------------------------------
# 5. transaction costs (H2): the equity curve compounds NET returns, so a
#    higher cost_bps strictly lowers ann_return while turnover is unchanged,
#    and a higher-turnover config pays strictly more.
# ---------------------------------------------------------------------------


def _rotating_bundles():
    """Two names whose momentum ranking flips mid-window (book rotates → real cost)."""
    n = len(VAL_DAYS)
    half = n // 2

    def win_path(i: int) -> float:
        return 100.0 + (0.20 * i if i < half else 0.20 * half + 0.01 * (i - half)) + (i % 5) * 0.3

    def late_path(i: int) -> float:
        return 100.0 + (0.01 * i if i < half else 0.01 * half + 0.40 * (i - half)) + (i % 5) * 0.3

    return {
        "WIN": _bundle_from_path(VAL_DAYS, win_path),
        "LATE": _bundle_from_path(VAL_DAYS, late_path),
    }


def test_costs_lower_net_return_turnover_unchanged():
    # Same synthetic bundles, two configs differing ONLY in cost_bps. The
    # higher-cost run yields a STRICTLY lower ann_return; turnover (a gross
    # reporting metric) is byte-identical.
    bundles = _rotating_bundles()
    base = _config(
        weights={"momentum": 1.0, "low_vol": 0.0, "reversal": 0.0, "value": 0.0, "quality": 0.0},
        top_n=1,
        max_weight=0.99,
    )
    cfg0 = dataclasses.replace(base, cost_bps=0.0)
    cfg100 = dataclasses.replace(base, cost_bps=100.0)

    res0 = backtest(bundles, cfg0, "val")
    res100 = backtest(bundles, cfg100, "val")

    # There IS turnover to charge against (the book rotates).
    assert res0["turnover"] > 0.0
    # Cost only touches the return path, never the (gross) turnover metric.
    assert res100["turnover"] == pytest.approx(res0["turnover"])
    # Charging cost strictly lowers the net annualized return.
    assert res100["ann_return"] < res0["ann_return"]


def test_zero_cost_path_unchanged_from_gross():
    # With cost_bps=0 the NET path must equal the pre-fix GROSS path exactly:
    # an explicit, hand-computed gross compounding of the period returns.
    bundles = _rotating_bundles()
    cfg = dataclasses.replace(
        _config(
            weights={"momentum": 1.0, "low_vol": 0.0, "reversal": 0.0, "value": 0.0, "quality": 0.0},
            top_n=1,
            max_weight=0.99,
        ),
        cost_bps=0.0,
    )
    res = backtest(bundles, cfg, "val")

    # Independently recompute the GROSS equity multiple from generate_holdings +
    # the same per-period return the backtest uses, then derive ann_return.
    from v2.self_evolve.backtest import PERIODS_PER_YEAR, START_CAPITAL, _period_return
    from v2.self_evolve.samples import rebalance_dates
    from v2.self_evolve.strategy_gen import generate_holdings

    day_set = {p.time[:10] for b in bundles.values() for p in b.prices}
    trading_days = sorted(day_set)
    dates = rebalance_dates("val", trading_days, freq="monthly")
    value = START_CAPITAL
    n_periods = 0
    for i in range(len(dates) - 1):
        w = generate_holdings(bundles, dates[i], cfg) or {}
        value *= 1.0 + _period_return(bundles, w, dates[i], dates[i + 1])
        n_periods += 1
    gross_ann = (value / START_CAPITAL) ** (PERIODS_PER_YEAR / n_periods) - 1.0

    assert res["ann_return"] == pytest.approx(gross_ann)


def test_higher_turnover_pays_strictly_more():
    # A higher-turnover config (top_n=1, which fully rotates) pays a strictly
    # larger cost drag at the same cost_bps than a low-turnover config (a single
    # eligible name → an essentially static book). So the (gross-net) ann_return
    # gap is strictly wider for the rotating book.
    rotating = _rotating_bundles()
    static = {"THE": _bundle_from_path(VAL_DAYS, lambda i: 100.0 + 0.05 * i + (i % 5) * 0.3)}

    rot_cfg = _config(
        weights={"momentum": 1.0, "low_vol": 0.0, "reversal": 0.0, "value": 0.0, "quality": 0.0},
        top_n=1,
        max_weight=0.99,
    )
    static_cfg = _config(top_n=5, max_weight=0.99)

    rot_gap = backtest(rotating, dataclasses.replace(rot_cfg, cost_bps=0.0), "val")["ann_return"] - backtest(rotating, dataclasses.replace(rot_cfg, cost_bps=100.0), "val")["ann_return"]
    static_gap = backtest(static, dataclasses.replace(static_cfg, cost_bps=0.0), "val")["ann_return"] - backtest(static, dataclasses.replace(static_cfg, cost_bps=100.0), "val")["ann_return"]

    assert rot_gap > static_gap
