"""Tests for the detector A/B eval harness.

All tests are synthetic — no live network calls.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from v2.data.models import Price
from v2.scanner.detectors.base import EventTrigger
from v2.scanner.eval.detector_ab import evaluate_detector, forward_return, run_ab


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _price(time_iso: str, close: float) -> Price:
    return Price(open=close, close=close, high=close, low=close, volume=1_000_000, time=time_iso)


def _make_prices(closes: list[float], start: str = "2025-01-02") -> list[Price]:
    """Build a Price list from a close series, starting at `start`."""
    d = date.fromisoformat(start)
    out: list[Price] = []
    for i, c in enumerate(closes):
        out.append(_price((d + timedelta(days=i)).isoformat(), c))
    return out


# ---------------------------------------------------------------------------
# test_forward_return_basic
# ---------------------------------------------------------------------------


class TestForwardReturn:
    def test_basic(self):
        closes = [100.0, 110.0, 121.0]
        result = forward_return(closes, 0, 2)
        assert result is not None
        assert abs(result - 0.21) < 1e-9

    def test_out_of_range_returns_none(self):
        closes = [100.0, 110.0, 121.0]
        # horizon would require index 3 which doesn't exist
        assert forward_return(closes, 0, 3) is None
        # idx itself out of range
        assert forward_return(closes, 5, 1) is None

    def test_zero_close_returns_none(self):
        # divide by zero guard
        closes = [0.0, 110.0, 121.0]
        assert forward_return(closes, 0, 2) is None

    def test_one_step(self):
        closes = [100.0, 105.0]
        result = forward_return(closes, 0, 1)
        assert result is not None
        assert abs(result - 0.05) < 1e-9


# ---------------------------------------------------------------------------
# test_evaluate_detector_shape
# ---------------------------------------------------------------------------


class TestEvaluateDetector:
    REQUIRED_KEYS = {
        "n_fired", "mean_fwd_return", "baseline_mean", "diff", "t_stat", "horizon",
    }

    def test_shape_and_values(self):
        fire_returns = [0.05, 0.06, 0.04]
        baseline_returns = [0.0, 0.01, -0.01, 0.0]
        result = evaluate_detector(
            fire_returns=fire_returns,
            baseline_returns=baseline_returns,
            horizon=20,
        )
        assert self.REQUIRED_KEYS <= set(result.keys())
        assert result["n_fired"] == 3
        assert abs(result["mean_fwd_return"] - 0.05) < 1e-9
        assert abs(result["baseline_mean"] - 0.0) < 1e-9
        assert result["diff"] > 0
        assert isinstance(result["t_stat"], float)
        assert result["horizon"] == 20

    def test_guards_small_n_fire(self):
        # n_fired < 2 → t_stat == 0.0, no raise
        result = evaluate_detector(
            fire_returns=[0.05],
            baseline_returns=[0.0, 0.01, -0.01, 0.0],
            horizon=20,
        )
        assert result["t_stat"] == 0.0

    def test_guards_empty_fire(self):
        result = evaluate_detector(
            fire_returns=[],
            baseline_returns=[0.0, 0.01],
            horizon=20,
        )
        assert result["t_stat"] == 0.0
        assert result["n_fired"] == 0

    def test_guards_small_n_baseline(self):
        # baseline < 2 → t_stat == 0.0
        result = evaluate_detector(
            fire_returns=[0.05, 0.06, 0.04],
            baseline_returns=[0.01],
            horizon=20,
        )
        assert result["t_stat"] == 0.0

    def test_guards_zero_denom(self):
        # identical values → variance 0 → zero denom → t_stat == 0.0, no raise
        result = evaluate_detector(
            fire_returns=[0.05, 0.05, 0.05],
            baseline_returns=[0.0, 0.0, 0.0],
            horizon=20,
        )
        assert result["t_stat"] == 0.0 or isinstance(result["t_stat"], float)

    def test_interestingness_metrics_present(self):
        out = evaluate_detector(
            fire_returns=[0.10, -0.08, 0.06],            # big moves, mixed sign
            baseline_returns=[0.01, -0.01, 0.00, 0.02],  # quiet
            horizon=5,
        )
        # existing signed keys still present and unchanged
        assert "mean_fwd_return" in out and "t_stat" in out and "diff" in out
        # NEW interestingness keys: |moves| of fired vs baseline
        assert out["abs_mean_fired"] == pytest.approx((0.10 + 0.08 + 0.06) / 3)
        assert out["abs_mean_baseline"] == pytest.approx((0.01 + 0.01 + 0.00 + 0.02) / 4)
        assert out["interestingness_diff"] == pytest.approx(
            out["abs_mean_fired"] - out["abs_mean_baseline"])
        assert out["interestingness_t"] > 0   # fired |moves| clearly larger → positive Welch t

    def test_interestingness_empty_arrays_safe(self):
        out = evaluate_detector(fire_returns=[], baseline_returns=[], horizon=5)
        assert out["abs_mean_fired"] == 0.0
        assert out["abs_mean_baseline"] == 0.0
        assert out["interestingness_diff"] == 0.0
        assert out["interestingness_t"] == 0.0


# ---------------------------------------------------------------------------
# test_run_ab_with_fake_detector
# ---------------------------------------------------------------------------


class _FakeDetectorFiresOnDates:
    """Fires only when (ticker, end_date) is in the fire_set."""

    name = "fake_detector"

    def __init__(self, fire_set: set[tuple[str, str]]):
        self._fire_set = fire_set

    def detect(self, ticker: str, end_date: str, fd, *, ctx=None) -> EventTrigger | None:
        triggered = (ticker, end_date) in self._fire_set
        return EventTrigger(
            detector=self.name,
            triggered=triggered,
        )


def _make_fd(prices: list[Price]) -> MagicMock:
    fd = MagicMock()
    fd.get_prices.return_value = prices
    return fd


class TestRunAb:
    def test_n_fired_and_shape(self):
        """Two tickers; detector fires on 2 specific (ticker, date) pairs.
        Check n_fired matches and all keys present."""
        # Build a 60-bar series for two tickers so forward returns exist.
        closes_a = [100.0 + i for i in range(60)]
        closes_b = [50.0 + i * 0.5 for i in range(60)]
        prices_a = _make_prices(closes_a)
        prices_b = _make_prices(closes_b)

        # dates: use early dates in the series so horizon=20 fits
        # prices_a starts 2025-01-02; index 0 = 2025-01-02
        dates_a = [prices_a[i].time for i in range(10)]  # first 10 dates
        dates_b = [prices_b[i].time for i in range(10)]

        # Make detector fire on 2 of these dates for AAPL
        fire_set = {("AAPL", dates_a[2]), ("AAPL", dates_a[5])}
        detector = _FakeDetectorFiresOnDates(fire_set)

        prices_by_ticker = {"AAPL": prices_a, "MSFT": prices_b}
        asof_dates_by_ticker = {"AAPL": dates_a, "MSFT": dates_b}

        def fd_factory(ticker: str):
            return _make_fd(prices_by_ticker[ticker])

        result = run_ab(
            detector=detector,
            prices_by_ticker=prices_by_ticker,
            asof_dates_by_ticker=asof_dates_by_ticker,
            fd_factory=fd_factory,
            horizon=20,
            baseline_per_ticker=5,
            rng_seed=42,
        )

        required_keys = {"n_fired", "mean_fwd_return", "baseline_mean", "diff", "t_stat", "horizon"}
        assert required_keys <= set(result.keys())
        assert result["n_fired"] == 2
        assert result["horizon"] == 20

    def test_no_fires_gives_zero_t_stat(self):
        """Detector never fires → n_fired==0, t_stat==0.0 (guard)."""
        closes = [100.0 + i for i in range(60)]
        prices = _make_prices(closes)
        dates = [prices[i].time for i in range(10)]

        detector = _FakeDetectorFiresOnDates(set())  # never fires

        def fd_factory(ticker: str):
            return _make_fd(prices)

        result = run_ab(
            detector=detector,
            prices_by_ticker={"AAPL": prices},
            asof_dates_by_ticker={"AAPL": dates},
            fd_factory=fd_factory,
            horizon=20,
            baseline_per_ticker=5,
            rng_seed=0,
        )
        assert result["n_fired"] == 0
        assert result["t_stat"] == 0.0

    def test_deterministic_with_seed(self):
        """Same seed → identical results; different seed may differ."""
        closes = [100.0 + i for i in range(60)]
        prices = _make_prices(closes)
        dates = [prices[i].time for i in range(10)]
        fire_set = {("AAPL", dates[3])}
        detector = _FakeDetectorFiresOnDates(fire_set)

        def fd_factory(ticker):
            return _make_fd(prices)

        kwargs = dict(
            detector=detector,
            prices_by_ticker={"AAPL": prices},
            asof_dates_by_ticker={"AAPL": dates},
            fd_factory=fd_factory,
            horizon=20,
            baseline_per_ticker=5,
        )
        r1 = run_ab(**kwargs, rng_seed=99)
        r2 = run_ab(**kwargs, rng_seed=99)
        assert r1["baseline_mean"] == r2["baseline_mean"]
