"""Offline TDD tests for scripts/eval_threshold_sweep.py.

Fully synthetic + offline: build ``Price`` bundles by hand, drive a ``_Thresh``
detector whose ctor takes a fire ``threshold`` and fires when a synthetic
"signal" (today's move vs the prior close) exceeds it. Bigger thresholds fire on
fewer, bigger moves — and those bigger moves are engineered to precede bigger
forward moves, so interestingness vs the random baseline RISES with the
threshold while the fire-rate FALLS.

NEVER calls ``main()`` / touches the network.
"""

from __future__ import annotations

import csv
from datetime import date, timedelta

from v2.data.models import Price
from v2.scanner.detectors.base import EventTrigger
from v2.scanner.eval.cached_asof_client import TickerBundle
from v2.scanner.eval.regimes import RegimeWindow

from scripts.eval_threshold_sweep import (
    CSV_COLUMNS,
    pick_knee,
    sweep_threshold,
    write_csv,
)


# ---------------------------------------------------------------------------
# Synthetic data builders
# ---------------------------------------------------------------------------


def _business_days(start: str, n: int) -> list[str]:
    """``n`` consecutive weekday ISO dates starting at ``start`` (skip weekends)."""
    out: list[str] = []
    d = date.fromisoformat(start)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _price(time: str, close: float) -> Price:
    """A flat-OHLC bar at ``close``; forward returns read adjusted_close."""
    return Price(
        open=close,
        close=close,
        high=close,
        low=close,
        volume=1_000_000,
        time=time,
        adjusted_close=close,
    )


class _Thresh:
    """Threshold-tunable fake detector.

    Its "signal" is the absolute one-bar move (|today/prev - 1|, in %). It fires
    when that move >= ``threshold``. A higher threshold therefore fires on fewer
    (bigger) moves — exactly the knob we want to sweep.
    """

    name = "t"

    def __init__(self, threshold) -> None:
        self.th = threshold

    def detect(self, ticker, end_date, fd, *, ctx=None):
        bars = fd.get_prices(ticker, "1900-01-01", end_date)
        if not bars or len(bars) < 2:
            return None
        prev = bars[-2].adjusted_close
        today = bars[-1].adjusted_close
        if not prev:
            return None
        move = abs(today / prev - 1.0) * 100.0  # percent move
        return EventTrigger(
            detector="t",
            triggered=move >= self.th,
            direction="bullish",
            severity_z=2.0,
        )


# Build one long synthetic series with three move-sizes:
#   * MOST bars: a tiny +0.2% wiggle (fires only at the loosest threshold) that
#     precedes a flat tape — uninteresting.
#   * SOME bars: a medium +3% move that precedes a +3% drift — modestly
#     interesting.
#   * FEW bars: a big +8% move that precedes a +12% run — very interesting.
# A higher fire threshold drops the wiggles first, then the medium moves, leaving
# only the big, high-payoff moves → interestingness rises, fire-rate falls.
_DATES = _business_days("2024-01-01", 260)

# 40-bar flat warm-up so detect() always sees history; events kept >=25 bars
# apart and >=20 bars before the end so forward returns exist.
_WARMUP = 40

# (index, one-bar move %, forward drift % applied over the next bar)
_SMALL = 0.2
_MEDIUM = 3.0
_BIG = 8.0

# Many small wiggles, a handful of medium moves, a couple of big moves.
_SMALL_IDX = list(range(_WARMUP + 2, 230, 2))  # ~94 small wiggles
_MEDIUM_IDX = [60, 90, 120, 150, 180, 210]  # 6 medium moves
_BIG_IDX = [70, 200]  # 2 big moves

# A small wiggle that lands on a medium/big bar is overridden by the larger move.
_SMALL_IDX = [i for i in _SMALL_IDX if i not in set(_MEDIUM_IDX) | set(_BIG_IDX)]

# Forward payoff after each move-size (applied to the NEXT bar's close so the
# fire bar's forward return captures it).
_SMALL_FWD = 1.000  # flat after a wiggle
_MEDIUM_FWD = 1.03  # +3% after a medium move
_BIG_FWD = 1.12  # +12% after a big move


def _build_series() -> list[Price]:
    """Series where bar i's close is set so |move at i| matches the planned size,
    and the bar AFTER a move carries the planned forward payoff."""
    moves = {}
    fwd = {}
    for i in _SMALL_IDX:
        moves[i] = _SMALL / 100.0
        fwd[i] = _SMALL_FWD
    for i in _MEDIUM_IDX:
        moves[i] = _MEDIUM / 100.0
        fwd[i] = _MEDIUM_FWD
    for i in _BIG_IDX:
        moves[i] = _BIG / 100.0
        fwd[i] = _BIG_FWD

    prices: list[Price] = []
    close = 100.0
    for i, day in enumerate(_DATES):
        # The move AT bar i is realized by bumping this bar's close vs the prior.
        if i in moves:
            close = close * (1.0 + moves[i])
        prices.append(_price(day, close))
        # The forward payoff is applied to the NEXT bar so the fire bar's fwd
        # return reflects it; then we settle back to flat for following bars.
        if i in fwd:
            close = close * fwd[i]
    return prices


_SERIES = _build_series()
BUNDLES = {"AAA": TickerBundle(ticker="AAA", prices=_SERIES)}
# SPY: flat series on the same dates → zero benchmark move (parity plumbing).
SPY = [_price(day, 400.0) for day in _DATES]

REGIME = RegimeWindow(
    name="synthetic",
    start=_DATES[_WARMUP],
    end=_DATES[240],
    spy_return=0.0,
    max_drawdown=0.0,
    trend_r2=0.0,
    n_bars=len(_DATES),
    label="CHOPPY",
)

# Ascending fire thresholds (percent move). 0.1 fires on everything incl. tiny
# wiggles; 5.0 fires only on the big moves.
_VALUES = [0.1, 1.0, 5.0]


def _make(v):
    return _Thresh(v)


def _rows_for(rows, value):
    return [r for r in rows if r["value"] == value]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_sweep_fire_rate_decreases():
    rows = sweep_threshold(_make, _VALUES, BUNDLES, SPY, [REGIME], horizon=5)
    by_val = {v: _rows_for(rows, v)[0] for v in _VALUES}
    rates = [by_val[v]["fire_rate"] for v in _VALUES]
    # Ascending thresholds → non-increasing fire-rate.
    for a, b in zip(rates, rates[1:]):
        assert b <= a + 1e-9, f"fire_rate not non-increasing: {rates}"
    # And it must actually fall, not stay flat: loosest fires more than strictest.
    assert rates[0] > rates[-1]


def test_sweep_interestingness_rises():
    rows = sweep_threshold(_make, _VALUES, BUNDLES, SPY, [REGIME], horizon=5)
    by_val = {v: _rows_for(rows, v)[0] for v in _VALUES}
    low = by_val[_VALUES[0]]["interestingness_diff"]
    high = by_val[_VALUES[-1]]["interestingness_diff"]
    # Strictest threshold keeps only the big, high-payoff moves → more interesting.
    assert high > low


def test_pick_knee_picks_loosest_significant():
    # Crafted rows: value 3.0 is the LOOSEST that is significant in >=2 regimes
    # AND under the fire-rate cap. 2.0 is significant but fires too often (over
    # cap); 4.0 also qualifies but is stricter than 3.0.
    rows = [
        # value 2.0 — significant but fire_rate over the 0.10 cap → rejected.
        {"value": 2.0, "regime": "r1", "fire_rate": 0.40, "interestingness_diff": 0.02, "interestingness_t": 3.0, "n_fired": 50},
        {"value": 2.0, "regime": "r2", "fire_rate": 0.45, "interestingness_diff": 0.02, "interestingness_t": 3.0, "n_fired": 50},
        # value 3.0 — significant in 2 regimes, mean fire_rate 0.08 <= cap → KNEE.
        {"value": 3.0, "regime": "r1", "fire_rate": 0.08, "interestingness_diff": 0.03, "interestingness_t": 2.5, "n_fired": 20},
        {"value": 3.0, "regime": "r2", "fire_rate": 0.08, "interestingness_diff": 0.03, "interestingness_t": 2.2, "n_fired": 20},
        # value 4.0 — also qualifies but stricter than 3.0.
        {"value": 4.0, "regime": "r1", "fire_rate": 0.04, "interestingness_diff": 0.05, "interestingness_t": 4.0, "n_fired": 8},
        {"value": 4.0, "regime": "r2", "fire_rate": 0.04, "interestingness_diff": 0.05, "interestingness_t": 4.0, "n_fired": 8},
    ]
    assert pick_knee(rows, fire_rate_cap=0.10, t_bar=2.0, min_regimes=2) == 3.0

    # All-insignificant → no sane threshold → None.
    dead = [
        {"value": 3.0, "regime": "r1", "fire_rate": 0.05, "interestingness_diff": -0.01, "interestingness_t": 0.3, "n_fired": 10},
        {"value": 3.0, "regime": "r2", "fire_rate": 0.05, "interestingness_diff": 0.00, "interestingness_t": 0.1, "n_fired": 10},
        {"value": 4.0, "regime": "r1", "fire_rate": 0.03, "interestingness_diff": 0.01, "interestingness_t": 1.0, "n_fired": 5},
        {"value": 4.0, "regime": "r2", "fire_rate": 0.03, "interestingness_diff": 0.01, "interestingness_t": 1.5, "n_fired": 5},
    ]
    assert pick_knee(dead, fire_rate_cap=0.10, t_bar=2.0, min_regimes=2) is None


def test_write_csv_roundtrip(tmp_path):
    rows = sweep_threshold(_make, _VALUES, BUNDLES, SPY, [REGIME], horizon=5)
    path = tmp_path / "threshold_sweep.csv"
    write_csv(rows, path, detector="t")
    with open(path, newline="", encoding="utf-8") as fh:
        back = list(csv.DictReader(fh))
    assert [*back[0].keys()] == list(CSV_COLUMNS)
    # Numeric columns round-trip as parseable floats.
    for r in back:
        float(r["fire_rate"])
        float(r["interestingness_diff"])
        float(r["interestingness_t"])
        float(r["n_fired"])
        assert r["detector"] == "t"
