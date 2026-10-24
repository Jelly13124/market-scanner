"""Tests for the per-detector x regime scorecard driver.

Synthetic ``Price`` lists (no network) drive a ``_FakeDetector`` whose fire
dates are explicit, so each test isolates one property of ``score_detector`` /
``score_all_detectors``:

  * interestingness > 0 when fired bars jump and baseline drifts ~0,
  * coverage accounting for empty-price + always-None-detector tickers,
  * direction-adjusted alpha flips sign for a bearish call that paid off,
  * one raising detector doesn't abort the whole sweep,
  * CSV round-trips with the documented column header.

The CRITICAL correctness rule under test: the detector decides through the
as-of-clamped client (blind to the future), but the forward return that scores
the fire is read from the ticker's FULL price list.
"""

from __future__ import annotations

from datetime import date, timedelta

from v2.data.models import Price
from v2.scanner.detectors.base import EventTrigger
from v2.scanner.eval.cached_asof_client import TickerBundle
from v2.scanner.eval.detector_scorecard import (
    CSV_COLUMNS,
    score_all_detectors,
    score_detector,
    write_detectors_csv,
)
from v2.scanner.eval.regimes import RegimeWindow


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _mk_prices(closes, start: str = "2023-01-02") -> list[Price]:
    """Build a ``Price`` list with consecutive calendar-daily dates.

    Calendar (not trading) days are fine — the scorecard only orders by
    ``time`` and indexes bars 0..n-1. ``adjusted_close`` mirrors ``close``.
    """
    d0 = date.fromisoformat(start)
    out: list[Price] = []
    for i, c in enumerate(closes):
        t = (d0 + timedelta(days=i)).isoformat()
        out.append(
            Price(
                open=c,
                high=c,
                low=c,
                close=c,
                volume=1000,
                time=t,
                adjusted_close=c,
            )
        )
    return out


def _date_at(start: str, i: int) -> str:
    return (date.fromisoformat(start) + timedelta(days=i)).isoformat()


def _regime(start: str, end: str, name: str = "test", label: str = "CHOPPY") -> RegimeWindow:
    return RegimeWindow(
        name=name,
        start=start,
        end=end,
        spy_return=0.0,
        max_drawdown=0.0,
        trend_r2=0.0,
        n_bars=0,
        label=label,
    )


class _FakeDetector:
    """Fires on an explicit set of as-of dates; exercises the as-of client."""

    name = "fake"

    def __init__(self, fire_on, direction: str = "bullish"):
        self._fire_on = set(fire_on)
        self._direction = direction

    def detect(self, ticker, end_date, fd, *, ctx=None):
        bars = fd.get_prices(ticker, "1900-01-01", end_date)  # as-of clamped
        if not bars:
            return None
        fired = end_date in self._fire_on
        return EventTrigger(detector="fake", triggered=fired, direction=self._direction)


class _RaisingDetector:
    name = "boom"

    def detect(self, ticker, end_date, fd, *, ctx=None):
        raise RuntimeError("kaboom")


# ---------------------------------------------------------------------------
# 1. Interestingness positive when fires precede a jump
# ---------------------------------------------------------------------------


def test_fired_detector_has_positive_interestingness():
    start = "2023-01-02"
    # Flat drift at 100 except: the day AFTER each fire date jumps +8%, then
    # reverts. Fire on two dates well inside the window so 5d fwd return exists.
    n = 60
    closes = [100.0] * n
    fire_dates = [_date_at(start, 10), _date_at(start, 25)]
    for fi in (10, 25):
        # Bar at fi is the fire bar (close 100); jump shows up over next 5d.
        for j in range(fi + 1, fi + 6):
            closes[j] = 108.0
        # revert after the window so baseline elsewhere stays ~flat
        for j in range(fi + 6, fi + 9):
            closes[j] = 100.0

    prices = _mk_prices(closes, start=start)
    bundle = TickerBundle(ticker="AAA", prices=prices)
    spy = _mk_prices([100.0] * n, start=start)  # flat SPY
    regime = _regime(start, _date_at(start, n - 1))

    det = _FakeDetector(fire_dates)
    rows = score_detector(det, regime, {"AAA": bundle}, spy)

    by_h = {r["horizon"]: r for r in rows}
    assert set(by_h) == {"5d", "20d"}
    r5 = by_h["5d"]
    assert r5["n_fired"] >= 1
    assert r5["interestingness_diff"] > 0
    assert r5["coverage"] == 1.0


# ---------------------------------------------------------------------------
# 2. Coverage accounting: empty prices + always-None detector
# ---------------------------------------------------------------------------


def test_no_data_ticker_zero_coverage():
    start = "2023-01-02"
    n = 40
    prices = _mk_prices([100.0] * n, start=start)
    regime = _regime(start, _date_at(start, n - 1))
    spy = _mk_prices([100.0] * n, start=start)

    # (a) Empty-price bundle → detector returns None (no bars) → coverage 0.0.
    empty_bundle = TickerBundle(ticker="EMPTY", prices=[])
    det = _FakeDetector([])  # never fires; but with data it would run clean
    rows = score_detector(det, regime, {"EMPTY": empty_bundle}, spy)
    assert all(r["coverage"] == 0.0 for r in rows)

    # (b) A detector that ALWAYS returns None even with data → coverage 0.0.
    class _AlwaysNone:
        name = "none"

        def detect(self, ticker, end_date, fd, *, ctx=None):
            return None

    good_bundle = TickerBundle(ticker="BBB", prices=prices)
    rows2 = score_detector(_AlwaysNone(), regime, {"BBB": good_bundle}, spy)
    assert all(r["coverage"] == 0.0 for r in rows2)


# ---------------------------------------------------------------------------
# 3. Bearish direction-adjust flips a drop into positive alpha
# ---------------------------------------------------------------------------


def test_direction_adjust_bearish_flips():
    start = "2023-01-02"
    n = 60
    # Price DROPS ~8% over the 5d after each fire date; flat SPY → alpha≈raw.
    closes = [100.0] * n
    fire_dates = [_date_at(start, 10), _date_at(start, 25)]
    for fi in (10, 25):
        for j in range(fi + 1, fi + 6):
            closes[j] = 92.0
        for j in range(fi + 6, fi + 9):
            closes[j] = 100.0

    prices = _mk_prices(closes, start=start)
    bundle = TickerBundle(ticker="AAA", prices=prices)
    spy = _mk_prices([100.0] * n, start=start)  # flat SPY so alpha≈raw return
    regime = _regime(start, _date_at(start, n - 1))

    det = _FakeDetector(fire_dates, direction="bearish")
    rows = score_detector(det, regime, {"AAA": bundle}, spy)
    by_h = {r["horizon"]: r for r in rows}
    r5 = by_h["5d"]
    assert r5["n_fired"] >= 1
    # A short that dropped is POSITIVE direction-adjusted alpha.
    assert r5["dir_alpha_mean"] > 0


# ---------------------------------------------------------------------------
# 4. score_all_detectors isolates a failing detector
# ---------------------------------------------------------------------------


def test_score_all_detectors_isolates_failures():
    start = "2023-01-02"
    n = 40
    prices = _mk_prices([100.0] * n, start=start)
    bundle = TickerBundle(ticker="AAA", prices=prices)
    spy = _mk_prices([100.0] * n, start=start)
    regime = _regime(start, _date_at(start, n - 1))

    good = _FakeDetector([_date_at(start, 10)])
    bad = _RaisingDetector()

    rows = score_all_detectors([bad, good], [regime], {"AAA": bundle}, spy)
    # The good detector still produced its two horizon rows; the sweep survived.
    names = {r["detector"] for r in rows}
    assert "fake" in names
    fake_rows = [r for r in rows if r["detector"] == "fake"]
    assert len(fake_rows) == 2


# ---------------------------------------------------------------------------
# 5. CSV round-trip
# ---------------------------------------------------------------------------


def test_write_csv_roundtrip(tmp_path):
    import csv

    start = "2023-01-02"
    n = 40
    prices = _mk_prices([100.0] * n, start=start)
    bundle = TickerBundle(ticker="AAA", prices=prices)
    spy = _mk_prices([100.0] * n, start=start)
    regime = _regime(start, _date_at(start, n - 1))

    rows = score_detector(_FakeDetector([_date_at(start, 10)]), regime, {"AAA": bundle}, spy)
    path = tmp_path / "detectors.csv"
    write_detectors_csv(rows, str(path))

    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        data_rows = list(reader)

    assert tuple(header) == CSV_COLUMNS
    assert len(data_rows) == len(rows)
