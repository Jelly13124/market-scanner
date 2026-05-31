"""Tests for the per-signal x regime cross-sectional rank-IC study.

Synthetic ``Price`` lists (no network) drive a controllable ``_FakeSignal`` whose
per-(ticker, date) value is a pure function, so each test isolates one property
of ``score_signal`` / ``score_all_signals``:

  * a factor whose rank EQUALS the forward-return rank → mean IC ≈ +1,
  * its negation → mean IC ≈ -1,
  * a fixed (deterministic) shuffle uncorrelated with returns → |mean IC| small,
  * a data-missing signal (value=0.0 + a "reason") → zero coverage / no IC dates,
  * CSV round-trips with the documented column header.

Construction trick for a date-independent ranking: ticker ``k`` grows at a
constant per-bar multiplicative rate that strictly increases with ``k``. Then the
``h``-day forward return ``(1+r_k)**h - 1`` is identical at every rebalance index
and strictly increasing in ``k`` — so any factor that ranks tickers by ``k`` is
perfectly rank-correlated with forward return at every date.

The CRITICAL correctness rule under test: the factor value is computed through the
as-of-clamped client (blind to the future), but the forward return that scores it
is read from the ticker's FULL price list.
"""

from __future__ import annotations

from datetime import date, timedelta

from v2.data.models import Price
from v2.models import SignalResult
from v2.scanner.eval.cached_asof_client import TickerBundle
from v2.scanner.eval.regimes import RegimeWindow
from v2.scanner.eval.signal_ic import (
    CSV_COLUMNS,
    score_all_signals,
    score_signal,
    write_signals_csv,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

N_TICKERS = 8
_START = "2023-01-02"
_N_BARS = 60  # plenty of bars for several weekly rebalances + a 20d forward tail


def _ticker(k: int) -> str:
    return f"T{k}"


def _mk_prices_drift(rate: float, start: str = _START, n: int = _N_BARS) -> list[Price]:
    """Constant per-bar multiplicative drift: close[i] = 100 * (1+rate)**i.

    ``adjusted_close`` mirrors ``close``. Calendar-daily dates are fine — the IC
    study only orders by ``time`` and indexes bars 0..n-1.
    """
    d0 = date.fromisoformat(start)
    out: list[Price] = []
    for i in range(n):
        c = 100.0 * ((1.0 + rate) ** i)
        t = (d0 + timedelta(days=i)).isoformat()
        out.append(
            Price(open=c, high=c, low=c, close=c, volume=1000, time=t, adjusted_close=c)
        )
    return out


def _build_universe() -> dict[str, TickerBundle]:
    """N tickers; ticker k drifts faster than k-1 → fwd-return rank == k at every date."""
    bundles: dict[str, TickerBundle] = {}
    for k in range(N_TICKERS):
        rate = 0.001 * (k + 1)  # 0.1%, 0.2%, ... per bar — strictly increasing in k
        bundles[_ticker(k)] = TickerBundle(ticker=_ticker(k), prices=_mk_prices_drift(rate))
    return bundles


def _date_at(start: str, i: int) -> str:
    return (date.fromisoformat(start) + timedelta(days=i)).isoformat()


def _regime(name: str = "test", label: str = "CHOPPY") -> RegimeWindow:
    return RegimeWindow(
        name=name,
        start=_START,
        end=_date_at(_START, _N_BARS - 1),
        spy_return=0.0,
        max_drawdown=0.0,
        trend_r2=0.0,
        n_bars=0,
        label=label,
    )


class _FakeSignal:
    """Returns a pure function of (ticker, end_date) as its value; never raises."""

    name = "fake"

    def __init__(self, value_fn):
        self._fn = value_fn  # (ticker, end_date) -> float

    def compute(self, ticker, end_date, fd):
        return SignalResult(
            signal_name="fake", value=self._fn(ticker, end_date), metadata={}
        )


class _MissingSignal:
    """Always reports the data-missing sentinel: value=0.0 with a "reason"."""

    name = "missing"

    def compute(self, ticker, end_date, fd):
        return SignalResult(
            signal_name="missing", value=0.0, metadata={"reason": "no data"}
        )


def _k_of(ticker: str) -> int:
    return int(ticker[1:])


# ---------------------------------------------------------------------------
# 1. Perfect factor: value rank == forward-return rank → mean IC ≈ +1
# ---------------------------------------------------------------------------


def test_perfect_factor_ic_near_plus_one():
    bundles = _build_universe()
    # value == k; forward return is also strictly increasing in k → IC ≈ +1.
    sig = _FakeSignal(lambda t, d: float(_k_of(t)))
    rows = score_signal(sig, _regime(), bundles)
    by_h = {r["horizon"]: r for r in rows}
    assert set(by_h) == {5, 20}
    r5 = by_h[5]
    assert r5["mean_ic"] > 0.9
    assert r5["n_dates"] >= 1
    assert r5["coverage"] == 1.0


# ---------------------------------------------------------------------------
# 2. Negated factor → mean IC ≈ -1
# ---------------------------------------------------------------------------


def test_negated_factor_ic_near_minus_one():
    bundles = _build_universe()
    sig = _FakeSignal(lambda t, d: -float(_k_of(t)))
    rows = score_signal(sig, _regime(), bundles)
    by_h = {r["horizon"]: r for r in rows}
    assert by_h[5]["mean_ic"] < -0.9


# ---------------------------------------------------------------------------
# 3. Shuffled factor (FIXED permutation) uncorrelated with returns → |IC| small
# ---------------------------------------------------------------------------


def test_shuffled_factor_ic_near_zero():
    bundles = _build_universe()
    # A fixed permutation of 0..7 chosen to have ~0 rank correlation with identity.
    # Spearman(identity, this) == 0 exactly for this literal.
    perm = {0: 3, 1: 5, 2: 0, 3: 6, 4: 1, 5: 7, 6: 2, 7: 4}
    sig = _FakeSignal(lambda t, d: float(perm[_k_of(t)]))
    rows = score_signal(sig, _regime(), bundles)
    by_h = {r["horizon"]: r for r in rows}
    assert abs(by_h[5]["mean_ic"]) < 0.5


# ---------------------------------------------------------------------------
# 4. Data-missing signal → zero coverage, no IC dates
# ---------------------------------------------------------------------------


def test_data_missing_signal_low_coverage():
    bundles = _build_universe()
    rows = score_signal(_MissingSignal(), _regime(), bundles)
    for r in rows:
        assert r["coverage"] == 0.0
        assert r["n_dates"] == 0
        assert r["mean_ic"] == 0.0
        assert r["ic_t"] == 0.0


# ---------------------------------------------------------------------------
# 5. score_all_signals isolates a failing signal; flat (signal x regime) list
# ---------------------------------------------------------------------------


def test_score_all_signals_isolates_failures():
    bundles = _build_universe()

    class _RaisingSignal:
        name = "boom"

        def compute(self, ticker, end_date, fd):
            raise RuntimeError("kaboom")

    good = _FakeSignal(lambda t, d: float(_k_of(t)))
    rows = score_all_signals([_RaisingSignal(), good], [_regime()], bundles)
    names = {r["signal"] for r in rows}
    assert "fake" in names
    assert len([r for r in rows if r["signal"] == "fake"]) == 2  # two horizons


# ---------------------------------------------------------------------------
# 6. CSV round-trip
# ---------------------------------------------------------------------------


def test_write_csv_roundtrip(tmp_path):
    import csv

    bundles = _build_universe()
    rows = score_signal(_FakeSignal(lambda t, d: float(_k_of(t))), _regime(), bundles)
    path = tmp_path / "signals.csv"
    write_signals_csv(rows, str(path))

    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        data_rows = list(reader)

    assert tuple(header) == CSV_COLUMNS
    assert len(data_rows) == len(rows)
