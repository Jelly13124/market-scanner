"""Offline TDD tests for scripts/eval_corroboration.py.

Fully synthetic + offline: build ``Price`` bundles by hand, drive two ``_Fake``
detectors that fire on hand-picked dates, and assert that the corroboration
measurement separates CO-FIRE bars (both detectors fire — engineered to precede
a big forward move) from SINGLE-FIRE bars (one detector — engineered to precede a
small move).

NEVER calls ``main()`` / touches the network.
"""

from __future__ import annotations

import csv
from datetime import date, timedelta

from v2.data.models import Price
from v2.scanner.detectors.base import EventTrigger
from v2.scanner.eval.cached_asof_client import TickerBundle
from v2.scanner.eval.regimes import RegimeWindow

from scripts.eval_corroboration import (
    CSV_COLUMNS,
    HORIZONS,
    _net_direction,
    run_all,
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
    """A flat-OHLC bar at ``close`` (fake detectors ignore OHLC).

    Forward returns read adjusted_close via ``close_of``.
    """
    return Price(
        open=close,
        close=close,
        high=close,
        low=close,
        volume=1_000_000,
        time=time,
        adjusted_close=close,
    )


class _Fake:
    """Stand-in detector that fires on a fixed set of dates.

    Mirrors the real ``detect`` surface: reads prices through the as-of client
    (returns ``None`` when there is no data) and emits a trigger on the
    configured fire dates with a fixed direction.
    """

    def __init__(self, name, fire_on, direction="bullish") -> None:
        self.name = name
        self._f = set(fire_on)
        self._d = direction

    def detect(self, ticker, end_date, fd, *, ctx=None):
        bars = fd.get_prices(ticker, "1900-01-01", end_date)
        if not bars:
            return None
        return EventTrigger(
            detector=self.name,
            triggered=end_date in self._f,
            direction=self._d,
            severity_z=2.0,
        )


# Build one long synthetic series.
#
#   * A 40-bar warm-up of flat price (100.0) gives every later fire bars of
#     history so detect() always sees data.
#   * CO-FIRE days (BOTH A and B fire, n_triggered=2) are followed by a +10%
#     jump over the next bar.
#   * SINGLE-FIRE days (only A OR only B, n_triggered=1) are followed by a small
#     +0.5% move.
#   * After every fire we pad >=20 forward bars so the 20d forward return exists
#     for both the fire and the random baseline.
_DATES = _business_days("2024-01-01", 220)

# Fire-day indices into _DATES (well past the warm-up, each >=25 bars apart, and
# >=20 bars before the end so forward returns exist).
_COFIRE_IDX = [60, 110]          # both A and B fire → bucket '2' → big move
_SINGLE_A_IDX = [80]             # only A fires → bucket '1' → small move
_SINGLE_B_IDX = [135]            # only B fires → bucket '1' → small move

COFIRE = [_DATES[i] for i in _COFIRE_IDX]
A_FIRES = [_DATES[i] for i in _COFIRE_IDX + _SINGLE_A_IDX]
B_FIRES = [_DATES[i] for i in _COFIRE_IDX + _SINGLE_B_IDX]

_BIG_JUMP = 1.10    # +10% on the bar after a co-fire day
_SMALL_JUMP = 1.005  # +0.5% on the bar after a single-fire day


def _build_series() -> list[Price]:
    prices: list[Price] = []
    close = 100.0
    cofire = set(_COFIRE_IDX)
    single = set(_SINGLE_A_IDX) | set(_SINGLE_B_IDX)
    for i, day in enumerate(_DATES):
        prices.append(_price(day, close))
        # Set NEXT bar's close: big jump after a co-fire bar, small jump after a
        # single-fire bar, flat otherwise.
        if i in cofire:
            close = close * _BIG_JUMP
        elif i in single:
            close = close * _SMALL_JUMP
    return prices


_SERIES = _build_series()
BUNDLES = {"AAA": TickerBundle(ticker="AAA", prices=_SERIES)}
# SPY: flat series on the same dates → zero benchmark move (parity plumbing).
SPY = [_price(day, 400.0) for day in _DATES]

REGIME = RegimeWindow(
    name="synthetic",
    start=_DATES[40],
    end=_DATES[200],
    spy_return=0.0,
    max_drawdown=0.0,
    trend_r2=0.0,
    n_bars=len(_DATES),
    label="CHOPPY",
)


def _row(rows, horizon: str, bucket: str) -> dict:
    for r in rows:
        if r["horizon"] == horizon and r["bucket"] == bucket:
            return r
    raise AssertionError(f"no row for horizon={horizon} bucket={bucket}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_corroboration_2plus_more_interesting():
    a = _Fake("det_a", A_FIRES, direction="bullish")
    b = _Fake("det_b", B_FIRES, direction="bullish")
    rows = run_all([a, b], BUNDLES, SPY, [REGIME])
    two = _row(rows, "5d", "2")
    one = _row(rows, "5d", "1")
    assert two["n"] >= 1 and one["n"] >= 1
    # Co-fire bars precede a real +10% move; single-fire bars precede a +0.5%
    # move, so the '2' bucket must look more interesting vs the random baseline.
    assert two["interestingness_diff"] > one["interestingness_diff"]


def test_net_direction():
    bull = EventTrigger(detector="x", triggered=True, direction="bullish")
    bear = EventTrigger(detector="y", triggered=True, direction="bearish")
    assert _net_direction([bull, bull, bear]) == ("bullish", 2)


def test_same_dir_split():
    # Two same-direction detectors co-fire on the same bars → their co-fire
    # events must land in the samedir (not mixeddir) row of the 2+ split.
    a = _Fake("det_a", A_FIRES, direction="bullish")
    b = _Fake("det_b", B_FIRES, direction="bullish")
    rows = run_all([a, b], BUNDLES, SPY, [REGIME])
    samedir = _row(rows, "5d", "2+_samedir")
    mixeddir = _row(rows, "5d", "2+_mixeddir")
    # All co-fires are bullish+bullish → samedir bucket gets them, mixeddir empty.
    assert samedir["n"] >= 1
    assert mixeddir["n"] == 0


def test_write_csv_roundtrip(tmp_path):
    a = _Fake("det_a", A_FIRES, direction="bullish")
    b = _Fake("det_b", B_FIRES, direction="bullish")
    rows = run_all([a, b], BUNDLES, SPY, [REGIME])
    path = tmp_path / "corroboration.csv"
    write_csv(rows, path)
    with open(path, newline="", encoding="utf-8") as fh:
        back = list(csv.DictReader(fh))
    assert [*back[0].keys()] == list(CSV_COLUMNS)
    # The numeric columns round-trip as parseable floats.
    for r in back:
        float(r["interestingness_diff"])
        float(r["n"])
