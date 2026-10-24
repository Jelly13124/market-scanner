"""Offline tests for config-driven portfolio generation (Task 4).

``generate_holdings`` turns as-of factor scores into a long-only, top-N,
vol-inverse-weighted book. These tests are pure Python — synthetic
``SimpleNamespace`` bundles, no network / data files / LLM. They pin the
load-bearing contract:

* only ``top_n`` names are held, weights sum to ~1.0, none exceeds ``max_weight``;
* the highest-composite names are the ones selected;
* within an equal-composite tie the LOWER-vol name gets MORE weight (vol-inverse);
* a name missing value/quality fundamentals is NOT dropped (price factors carry it);
* a zero-std factor never divides by zero (std-floor invariant) and never crashes;
* empty / degenerate universes return ``{}`` (never raises).

The duck-typed bundle shape (``.prices`` with ``.time`` / ``.close`` / ``.volume``)
is exactly what the liquidity + factor layers read via ``getattr``.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from v2.self_evolve.config import StrategyConfig
from v2.self_evolve.strategy_gen import generate_holdings


# ---------------------------------------------------------------------------
# Synthetic-bundle builders
# ---------------------------------------------------------------------------


def _price(d: str, close: float, volume: float) -> SimpleNamespace:
    return SimpleNamespace(time=d, close=close, volume=volume)


def _li(report_period: str, **fields) -> SimpleNamespace:
    """A raw line-item record (``report_period`` + dynamic statement fields).

    ``value`` (E/P) and ``quality`` (ROE = EPS/BVPS) are computed from these line
    items; the factor layer reads each field via ``getattr``.
    """
    return SimpleNamespace(report_period=report_period, **fields)


def _series(
    asof: date,
    n: int,
    *,
    start_price: float,
    step: float,
    jitter: float = 0.0,
    volume: float = 1_000_000.0,
) -> list[SimpleNamespace]:
    """``n`` consecutive calendar-day bars ENDING on ``asof``.

    Close = ``start_price + i*step + (i % 5)*jitter`` so a nonzero ``jitter`` gives
    a real, nonzero realized vol (needed for the vol-inverse weight to be defined).
    Daily bars make the factor layer's offset arithmetic land exactly on targets.
    """
    start = asof - timedelta(days=n - 1)
    bars = []
    for i in range(n):
        close = start_price + i * step + (i % 5) * jitter
        bars.append(_price((start + timedelta(days=i)).isoformat(), close, volume))
    return bars


def _config(
    *,
    weights=None,
    top_n=30,
    max_weight=0.05,
    advol_pct=0.20,
    mktcap_pct=0.20,
    momentum_days=180,
    vol_days=30,
    reversal_days=10,
) -> StrategyConfig:
    """A real ``StrategyConfig`` (weights are sum-normalized in ``__post_init__``)."""
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


ASOF = "2020-12-31"
_ASOF_D = date(2020, 12, 31)


# ---------------------------------------------------------------------------
# 1. top_n selection + sum-to-1 + per-name cap + highest composites win
# ---------------------------------------------------------------------------


def test_topn_selection_weights_sum_and_cap():
    # Six names with cleanly separated momentum (via per-name step), all liquid &
    # equally jittered (so vol is comparable). Pure-momentum weights → the steepest
    # ramps must be the ones selected; top_n=3 keeps only the top three.
    steps = {"A": 1.0, "B": 0.8, "C": 0.6, "D": 0.4, "E": 0.2, "F": 0.05}
    bundles = {t: SimpleNamespace(prices=_series(_ASOF_D, 400, start_price=100.0, step=s, jitter=0.3), metrics_history=[]) for t, s in steps.items()}
    cfg = _config(
        weights={"momentum": 1.0, "low_vol": 0.0, "reversal": 0.0, "value": 0.0, "quality": 0.0},
        top_n=3,
        max_weight=0.60,
        advol_pct=0.0,  # do not drop anyone on liquidity for this selection test
        mktcap_pct=0.0,
    )
    holdings = generate_holdings(bundles, ASOF, cfg)

    assert len(holdings) == 3
    assert set(holdings) == {"A", "B", "C"}  # the three steepest momentum ramps
    assert sum(holdings.values()) == pytest.approx(1.0)
    assert all(w <= cfg.max_weight + 1e-9 for w in holdings.values())
    assert all(w > 0.0 for w in holdings.values())


def test_cap_binds_and_renormalizes():
    # max_weight forces a flatter book than the raw vol-inverse tilt would produce.
    steps = {"A": 1.0, "B": 0.9, "C": 0.8, "D": 0.7, "E": 0.6}
    bundles = {t: SimpleNamespace(prices=_series(_ASOF_D, 400, start_price=100.0, step=s, jitter=0.3), metrics_history=[]) for t, s in steps.items()}
    cfg = _config(
        weights={"momentum": 1.0, "low_vol": 0.0, "reversal": 0.0, "value": 0.0, "quality": 0.0},
        top_n=5,
        max_weight=0.25,  # < 1/4, so the cap MUST bind on at least one name
        advol_pct=0.0,
        mktcap_pct=0.0,
    )
    holdings = generate_holdings(bundles, ASOF, cfg)
    assert len(holdings) == 5
    assert sum(holdings.values()) == pytest.approx(1.0)
    assert all(w <= cfg.max_weight + 1e-9 for w in holdings.values())


# ---------------------------------------------------------------------------
# 2. vol-inverse: equal composite, lower vol → MORE weight
# ---------------------------------------------------------------------------


def test_inverse_vol_lower_vol_gets_more_weight():
    # Two names with IDENTICAL price path shape (same momentum/reversal composite)
    # but different realized vol: LO has small jitter, HI has large jitter. Under a
    # vol-inverse weighting LO (lower vol) must receive strictly more weight.
    lo = SimpleNamespace(prices=_series(_ASOF_D, 400, start_price=100.0, step=0.5, jitter=0.2), metrics_history=[])
    hi = SimpleNamespace(prices=_series(_ASOF_D, 400, start_price=100.0, step=0.5, jitter=5.0), metrics_history=[])
    bundles = {"LO": lo, "HI": hi}
    cfg = _config(
        # Weight only momentum+reversal so the (identical) price RAMP drives the
        # composite tie; low_vol is excluded so vol enters ONLY via the weighting.
        weights={"momentum": 0.5, "low_vol": 0.0, "reversal": 0.5, "value": 0.0, "quality": 0.0},
        top_n=2,
        max_weight=0.99,
        advol_pct=0.0,
        mktcap_pct=0.0,
    )
    holdings = generate_holdings(bundles, ASOF, cfg)
    assert set(holdings) == {"LO", "HI"}
    assert holdings["LO"] > holdings["HI"]
    assert sum(holdings.values()) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 3. a name with None value/quality is NOT dropped
# ---------------------------------------------------------------------------


def test_missing_fundamentals_not_dropped():
    # WITHFUND has fundamentals; NOFUND has none (value/quality -> None). With value
    # weighted heavily, NOFUND still survives on a neutral-0 z for the missing factor
    # plus its price factors. With top_n large enough to hold both, NOFUND is present.
    withfund = SimpleNamespace(
        prices=_series(_ASOF_D, 400, start_price=100.0, step=0.5, jitter=0.3),
        metrics_history=[],
        line_items_history=[_li((_ASOF_D - timedelta(days=90)).isoformat(), earnings_per_share=20.0, book_value_per_share=100.0)],
    )
    nofund = SimpleNamespace(
        prices=_series(_ASOF_D, 400, start_price=100.0, step=0.6, jitter=0.3),
        metrics_history=[],
    )
    bundles = {"WITHFUND": withfund, "NOFUND": nofund}
    cfg = _config(
        weights={"momentum": 0.2, "low_vol": 0.0, "reversal": 0.0, "value": 0.4, "quality": 0.4},
        top_n=2,
        max_weight=0.99,
        advol_pct=0.0,
        mktcap_pct=0.0,
    )
    holdings = generate_holdings(bundles, ASOF, cfg)
    # The fundamental-less name is eligible and held (not silently dropped).
    assert "NOFUND" in holdings
    assert set(holdings) == {"WITHFUND", "NOFUND"}
    assert sum(holdings.values()) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 4. zero-std factor → no divide-by-zero, no crash
# ---------------------------------------------------------------------------


def test_zero_std_factor_no_divide_by_zero():
    # Every name shares an IDENTICAL price path → identical momentum/low_vol/reversal
    # across the cross-section → those factors have zero std. The z-score layer must
    # floor std (contribute 0) rather than divide by zero. Distinguish names only by
    # quality so a winner still exists; the book must be well-formed.
    bundles = {}
    for i, t in enumerate(["A", "B", "C", "D"]):
        # ROE = EPS / BVPS = (10 + 5i) / 100 → 0.10, 0.15, 0.20, 0.25 (C, D highest).
        bundles[t] = SimpleNamespace(
            prices=_series(_ASOF_D, 400, start_price=100.0, step=0.5, jitter=0.3),
            metrics_history=[],
            line_items_history=[_li((_ASOF_D - timedelta(days=90)).isoformat(), earnings_per_share=10.0 + 5.0 * i, book_value_per_share=100.0)],
        )
    cfg = _config(
        # momentum/low_vol/reversal are identical (zero std); quality breaks the tie.
        weights={"momentum": 0.3, "low_vol": 0.3, "reversal": 0.0, "value": 0.0, "quality": 0.4},
        top_n=2,
        max_weight=0.99,
        advol_pct=0.0,
        mktcap_pct=0.0,
    )
    holdings = generate_holdings(bundles, ASOF, cfg)  # must not raise
    assert len(holdings) == 2
    assert sum(holdings.values()) == pytest.approx(1.0)
    # Highest-ROE names (C, D) win once the tied factors contribute nothing.
    assert set(holdings) == {"C", "D"}


def test_all_factors_zero_std_still_builds_a_book():
    # The fully degenerate case: identical on EVERY factor (no fundamentals at all).
    # Composite is identically 0 for all → ranking is a no-op → top_n still selected,
    # weighted purely by vol-inverse, summing to 1.0. No crash, non-empty book.
    bundles = {t: SimpleNamespace(prices=_series(_ASOF_D, 400, start_price=100.0, step=0.5, jitter=0.3), metrics_history=[]) for t in ["A", "B", "C"]}
    cfg = _config(top_n=2, max_weight=0.99, advol_pct=0.0, mktcap_pct=0.0)
    holdings = generate_holdings(bundles, ASOF, cfg)
    assert len(holdings) == 2
    assert sum(holdings.values()) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 5. empty / degenerate universe → {} (never raises)
# ---------------------------------------------------------------------------


def test_empty_bundles_returns_empty():
    assert generate_holdings({}, ASOF, _config()) == {}


def test_single_illiquid_name_no_crash():
    # One name with too-short history → no factors → empty book, no crash.
    one = {"ONE": SimpleNamespace(prices=[_price("2020-12-31", 50.0, 1.0)], metrics_history=[])}
    assert generate_holdings(one, ASOF, _config()) == {}


def test_unparseable_asof_returns_empty():
    bundles = {"A": SimpleNamespace(prices=_series(_ASOF_D, 400, start_price=100.0, step=0.5, jitter=0.3), metrics_history=[])}
    assert generate_holdings(bundles, "not-a-date", _config()) == {}


def test_unparseable_asof_warns_with_type(caplog):
    # M1: a non-ISO asof (e.g. a datetime.date, which _parse_iso can't subscript)
    # must NOT return an empty book SILENTLY — that is indistinguishable from a
    # legitimate no-signal week. It returns {} AND logs a WARNING naming the type.
    import logging

    bundles = {"A": SimpleNamespace(prices=_series(_ASOF_D, 400, start_price=100.0, step=0.5, jitter=0.3), metrics_history=[])}
    with caplog.at_level(logging.WARNING, logger="v2.self_evolve.strategy_gen"):
        result = generate_holdings(bundles, _ASOF_D, _config())  # a date, not an ISO string
    assert result == {}
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    # The warning names the offending type so the footgun is diagnosable.
    assert "date" in caplog.text


def test_happy_path_iso_string_emits_no_warning(caplog):
    # The normal ISO-string call path is unchanged and stays quiet.
    import logging

    bundles = {"A": SimpleNamespace(prices=_series(_ASOF_D, 400, start_price=100.0, step=0.5, jitter=0.3), metrics_history=[])}
    with caplog.at_level(logging.WARNING, logger="v2.self_evolve.strategy_gen"):
        generate_holdings(bundles, ASOF, _config())
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_never_raises_on_garbage_bundle():
    # A bundle missing .prices entirely must be tolerated (defensive contract).
    bundles = {"BAD": SimpleNamespace(metrics_history=[])}
    assert generate_holdings(bundles, ASOF, _config()) == {}


# ---------------------------------------------------------------------------
# 6. liquidity filter: thin names are dropped when the percentile bites
# ---------------------------------------------------------------------------


def test_liquidity_filter_drops_thin_names():
    # Three fat names (high volume) + one razor-thin name. advol_pct=0.20 drops the
    # bottom 20% by avg dollar volume → the thin name must NOT appear in the book.
    fat = {t: SimpleNamespace(prices=_series(_ASOF_D, 400, start_price=100.0, step=0.5, jitter=0.3, volume=5_000_000.0), metrics_history=[]) for t in ["A", "B", "C"]}
    thin = {"THIN": SimpleNamespace(prices=_series(_ASOF_D, 400, start_price=100.0, step=0.5, jitter=0.3, volume=1.0), metrics_history=[])}
    bundles = {**fat, **thin}
    cfg = _config(top_n=10, max_weight=0.99, advol_pct=0.20, mktcap_pct=0.0)
    holdings = generate_holdings(bundles, ASOF, cfg)
    assert "THIN" not in holdings
    assert set(holdings) == {"A", "B", "C"}
    assert sum(holdings.values()) == pytest.approx(1.0)


def test_degenerate_liquidity_keeps_all():
    # All names share an IDENTICAL price path AND volume → identical dollar volume →
    # the percentile cut is degenerate (all values equal). Rather than dropping
    # everyone (empty book), the filter keeps them all.
    bundles = {t: SimpleNamespace(prices=_series(_ASOF_D, 400, start_price=100.0, step=0.5, jitter=0.3, volume=2_000_000.0), metrics_history=[]) for t in ["A", "B", "C"]}
    cfg = _config(top_n=10, max_weight=0.99, advol_pct=0.50, mktcap_pct=0.50)
    holdings = generate_holdings(bundles, ASOF, cfg)
    assert set(holdings) == {"A", "B", "C"}
    assert sum(holdings.values()) == pytest.approx(1.0)
