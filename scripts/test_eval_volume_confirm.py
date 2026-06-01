"""Offline TDD tests for scripts/eval_volume_confirm.py.

Fully synthetic + offline: build ``Price`` bundles by hand, drive a ``_FakeIM``
detector that fires on hand-picked dates, and assert that the volume-split
measurement separates high-volume fires (engineered to precede a big forward
move) from low-volume fires (engineered to precede ~no move).

NEVER calls ``main()`` / touches the network.
"""

from __future__ import annotations

import csv
from datetime import date, timedelta

from v2.data.models import Price
from v2.scanner.detectors.base import EventTrigger
from v2.scanner.eval.cached_asof_client import TickerBundle
from v2.scanner.eval.regimes import RegimeWindow

from scripts.eval_volume_confirm import (
    CSV_COLUMNS,
    HORIZONS,
    run_all,
    run_volume_confirm,
    volume_z,
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


def _price(time: str, close: float, volume: float) -> Price:
    """A flat-OHLC bar at ``close`` with the given volume.

    The fake detector ignores OHLC, so open==high==low==close keeps it simple;
    forward returns read adjusted_close via ``close_of``.
    """
    return Price(
        open=close,
        close=close,
        high=close,
        low=close,
        volume=int(volume),
        time=time,
        adjusted_close=close,
    )


class _FakeIM:
    """Stand-in for IntradayMoveDetector that fires on a fixed set of dates.

    Mirrors the real ``detect`` surface: reads prices through the as-of client
    (returns ``None`` when there is no data) and emits a bullish trigger on the
    configured fire dates.
    """

    name = "intraday_move"

    def __init__(self, fire_on) -> None:
        self._f = set(fire_on)

    def detect(self, ticker, end_date, fd, *, ctx=None):
        bars = fd.get_prices(ticker, "1900-01-01", end_date)
        if not bars:
            return None
        return EventTrigger(
            detector="intraday_move",
            triggered=end_date in self._f,
            direction="bullish",
        )


# Build one long synthetic series.
#
#   * A 40-bar warm-up of flat price (100.0) + flat baseline volume (1,000,000)
#     gives every later fire ≥20 trailing bars for the vol-z window.
#   * HIGH fire days carry a 5x volume spike and are followed by a +8% jump.
#   * LOW fire days carry baseline volume and are followed by ~0% move.
#   * After every fire we pad ≥20 forward bars so the 20d forward return exists
#     for both the fire and the random baseline.
_DATES = _business_days("2024-01-01", 220)
_BASE_VOL = 1_000_000.0
_SPIKE_VOL = 5_000_000.0

# Fire-day indices into _DATES (well past the warm-up, each ≥25 bars apart so
# trailing windows don't overlap a prior spike, and ≥20 bars before the end).
HIGH = [_DATES[60], _DATES[110]]
LOW = [_DATES[85], _DATES[135]]
_HIGH_IDX = {60, 110}
_LOW_IDX = {85, 135}


def _build_series() -> list[Price]:
    prices: list[Price] = []
    close = 100.0
    for i, day in enumerate(_DATES):
        vol = _BASE_VOL
        if i in _HIGH_IDX:
            vol = _SPIKE_VOL
        prices.append(_price(day, close, vol))
        # Set NEXT bar's close: +8% drift over the 5 bars after a high-vol fire,
        # flat after a low-vol fire, flat otherwise.
        if i in _HIGH_IDX:
            close = close * 1.08
    return prices


_SERIES = _build_series()
BUNDLES = {"AAA": TickerBundle(ticker="AAA", prices=_SERIES)}
# SPY: flat series on the same dates → zero benchmark move (not used by _FakeIM,
# but run_volume_confirm needs a SPY for the signed/alpha plumbing parity).
SPY = [_price(day, 400.0, _BASE_VOL) for day in _DATES]

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


def test_high_vol_bucket_more_interesting():
    rows = run_all(_FakeIM(fire_on=HIGH + LOW), BUNDLES, SPY, [REGIME], vol_threshold=1.0)
    h = _row(rows, "5d", "high_vol")
    l = _row(rows, "5d", "low_vol")
    assert h["n"] >= 1 and l["n"] >= 1
    # High-vol fires precede a real +8% move; low-vol fires precede ~0 move, so
    # the high-vol bucket must look more interesting vs the random baseline.
    assert h["interestingness_diff"] > l["interestingness_diff"]


def test_volume_z_floor():
    # Identical trailing volumes → std == 0 → must fall back to the 10%-of-mean
    # floor (NOT a div-by-zero / inf). today == mean → z == 0 exactly.
    flat = [1_000_000.0] * 25
    z = volume_z(flat, asof_idx=24, window=20)
    assert z == 0.0

    # today above a flat trailing window: z = (1.2e6 - 1e6) / (0.10 * 1e6) = 2.0
    bumped = [1_000_000.0] * 24 + [1_200_000.0]
    z2 = volume_z(bumped, asof_idx=24, window=20)
    assert abs(z2 - 2.0) < 1e-9

    # Too few trailing bars → None (cannot form the window).
    assert volume_z([1.0, 2.0, 3.0], asof_idx=2, window=20) is None


def test_write_csv_roundtrip(tmp_path):
    rows = run_all(_FakeIM(fire_on=HIGH + LOW), BUNDLES, SPY, [REGIME], vol_threshold=1.0)
    path = tmp_path / "volume_confirm.csv"
    write_csv(rows, path)
    with open(path, newline="", encoding="utf-8") as fh:
        back = list(csv.DictReader(fh))
    assert [*back[0].keys()] == list(CSV_COLUMNS)
    # One row per horizon x bucket.
    assert len(back) == len(HORIZONS) * 2
    # The numeric columns round-trip as parseable floats.
    for r in back:
        float(r["interestingness_diff"])
        float(r["n"])
