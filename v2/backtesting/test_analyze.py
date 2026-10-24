"""Unit tests for v2/backtesting/analyze.py.

Targets the analysis primitives — bootstrap CI math, independence
counting, BREAK horizon parsing, INSDR strict-subset filter, regime
classification. None of these tests hit the network; the regime test
injects a synthetic SPY price list rather than fetching live.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import numpy as np
import pytest

from v2.backtesting.analyze import (
    Row,
    _bh_adjust,
    _break_horizons_for,
    _build_regime_map,
    _direction_adjust,
    _independence_check,
    _raw_pvalue,
    bootstrap_ci,
    load_rows,
)


def _row(
    *,
    ticker: str = "AAPL",
    scan_date: str = "2024-09-03",
    rank: int = 1,
    direction: str = "bullish",
    triggered: list[str] | None = None,
    components: dict[str, dict[str, float]] | None = None,
    alpha_5d: float | None = None,
    alpha_20d: float | None = None,
    alpha_63d: float | None = None,
    composite: float = 75.0,
) -> Row:
    return Row(
        scan_date=scan_date,
        ticker=ticker,
        rank=rank,
        composite_score=composite,
        direction=direction,
        event_severity=2.0,
        n_detectors_triggered=len(triggered or []),
        triggered_detectors=list(triggered or []),
        triggered_components=components or {},
        close_at_scan=100.0,
        ret={1: None, 5: alpha_5d, 20: alpha_20d, 63: alpha_63d},
        bench_ret={1: None, 5: 0.0, 20: 0.0, 63: 0.0},
        alpha={1: None, 5: alpha_5d, 20: alpha_20d, 63: alpha_63d},
        dir_ret_5d=alpha_5d,
        dir_alpha_5d=alpha_5d,
    )


# ---------------------------------------------------------------------------
# bootstrap_ci
# ---------------------------------------------------------------------------


class TestBootstrapCI:
    def test_known_normal_sample_ci_brackets_mean(self):
        """N(0, 1) sample of 500 → CI should bracket 0 most of the time."""
        rng = np.random.default_rng(seed=123)
        sample = rng.normal(0.0, 1.0, size=500).tolist()
        mean, lo, hi = bootstrap_ci(sample, n_resamples=2000)
        assert lo < mean < hi
        # 95% CI on N(0,1) mean with n=500: SE ≈ 0.045, so CI ~±0.088
        assert abs(mean) < 0.15
        assert hi - lo < 0.5  # tight enough at n=500

    def test_empty_input_all_none(self):
        assert bootstrap_ci([], n_resamples=100) == (None, None, None)

    def test_single_sample_no_ci(self):
        mean, lo, hi = bootstrap_ci([0.42], n_resamples=100)
        assert mean == pytest.approx(0.42)
        assert lo is None and hi is None

    def test_constant_sample_zero_width_ci(self):
        """All values equal → CI width should be ≈ 0 (no resample variance)."""
        mean, lo, hi = bootstrap_ci([0.05] * 50, n_resamples=1000)
        assert mean == pytest.approx(0.05)
        assert lo == pytest.approx(0.05, abs=1e-9)
        assert hi == pytest.approx(0.05, abs=1e-9)


# ---------------------------------------------------------------------------
# Independence counting
# ---------------------------------------------------------------------------


class TestIndependenceCheck:
    def test_dense_repeats_count_as_one(self):
        """Same ticker on 3 consecutive days, min_gap_days=5 → only 1 event."""
        rows = [
            _row(ticker="PDD", scan_date="2024-09-03"),
            _row(ticker="PDD", scan_date="2024-09-04"),
            _row(ticker="PDD", scan_date="2024-09-05"),
        ]
        n, _ = _independence_check(rows, min_gap_days=5)
        assert n == 1

    def test_well_separated_repeats_count_independently(self):
        """Same ticker every 10 calendar days → all independent."""
        rows = [
            _row(ticker="PDD", scan_date="2024-09-03"),
            _row(ticker="PDD", scan_date="2024-09-13"),
            _row(ticker="PDD", scan_date="2024-09-23"),
        ]
        n, _ = _independence_check(rows, min_gap_days=5)
        assert n == 3

    def test_different_tickers_independent(self):
        rows = [
            _row(ticker="AAPL", scan_date="2024-09-03"),
            _row(ticker="MSFT", scan_date="2024-09-03"),
            _row(ticker="NVDA", scan_date="2024-09-03"),
        ]
        n, _ = _independence_check(rows, min_gap_days=5)
        assert n == 3


# ---------------------------------------------------------------------------
# BREAK horizon parsing
# ---------------------------------------------------------------------------


class TestBreakHorizons:
    def test_uses_direct_horizons_broken_list(self):
        r = _row(
            triggered=["breakout_52w"],
            components={"breakout_52w": {"horizons_broken": [63, 126]}},
        )
        assert _break_horizons_for(r) == [63, 126]

    def test_falls_back_to_n_bullish_count(self):
        """When horizons_broken not present, infer from n_bullish_horizons."""
        r = _row(
            triggered=["breakout_52w"],
            components={"breakout_52w": {"n_bullish_horizons": 3, "n_bearish_horizons": 0}},
        )
        assert _break_horizons_for(r) == [63, 126, 252]

    def test_returns_none_when_break_did_not_fire(self):
        r = _row(triggered=["earnings_surprise"], components={"earnings_surprise": {}})
        assert _break_horizons_for(r) is None

    def test_single_horizon_n_bull_1(self):
        r = _row(
            triggered=["breakout_52w"],
            components={"breakout_52w": {"n_bullish_horizons": 1, "n_bearish_horizons": 0}},
        )
        assert _break_horizons_for(r) == [63]


# ---------------------------------------------------------------------------
# Regime classification (synthetic SPY)
# ---------------------------------------------------------------------------


def _spy_bars(*, start_iso: str, returns: list[float], base: float = 400.0):
    """Build a SPY-like Price list with daily compounded returns starting at base."""
    from datetime import datetime, timedelta
    from v2.data.models import Price
    out: list[Price] = []
    price = base
    d = datetime.strptime(start_iso, "%Y-%m-%d").date()
    for r in returns:
        # weekdays only
        while d.weekday() >= 5:
            d += timedelta(days=1)
        price *= 1.0 + r
        out.append(Price(
            open=price, close=price, high=price, low=price,
            volume=10_000_000, time=d.isoformat(), adjusted_close=price,
        ))
        d += timedelta(days=1)
    return out


class TestRegimeMap:
    def test_up_regime_when_trailing_above_threshold(self):
        # 25 days, all +0.5% per day → 20d trailing ≈ +10% → up
        bars = _spy_bars(start_iso="2024-09-01", returns=[0.005] * 25)
        scan_date = bars[-1].time[:10]
        reg = _build_regime_map(
            [scan_date], threshold=0.01, spy_prices_override=bars,
        )
        assert reg.get(scan_date) == "up"

    def test_down_regime_when_trailing_below_threshold(self):
        bars = _spy_bars(start_iso="2024-09-01", returns=[-0.005] * 25)
        scan_date = bars[-1].time[:10]
        reg = _build_regime_map(
            [scan_date], threshold=0.01, spy_prices_override=bars,
        )
        assert reg.get(scan_date) == "down"

    def test_chop_when_within_threshold(self):
        # 25 days of tiny ±0.0005 → trailing ≈ 0 → chop
        bars = _spy_bars(start_iso="2024-09-01",
                         returns=[0.0005, -0.0005] * 13)[:25]
        scan_date = bars[-1].time[:10]
        reg = _build_regime_map(
            [scan_date], threshold=0.01, spy_prices_override=bars,
        )
        assert reg.get(scan_date) == "chop"

    def test_returns_empty_when_too_few_bars(self):
        bars = _spy_bars(start_iso="2024-09-01", returns=[0.001] * 10)
        reg = _build_regime_map(
            ["2024-09-15"], threshold=0.01, spy_prices_override=bars,
        )
        assert reg == {}


# ---------------------------------------------------------------------------
# CSV loader
# ---------------------------------------------------------------------------


class TestLoadRows:
    def test_parses_components_json_column(self, tmp_path):
        csv_path = tmp_path / "tiny.csv"
        rows_data = [
            {
                "scan_date": "2024-09-03", "ticker": "AAPL", "rank": 1,
                "composite_score": 85.5, "direction": "bullish",
                "event_severity": 3.5,
                "n_detectors_triggered": 2,
                "triggered_detectors": "earnings_surprise|intraday_move",
                "triggered_components_json": json.dumps({
                    "earnings_surprise": {"raw_z": 2.5},
                    "intraday_move": {"z_cvo": 3.1, "benchmark_used": 1.0},
                }),
                "close_at_scan": 175.0,
                "ret_1d": 0.012, "ret_5d": 0.034, "ret_20d": 0.05, "ret_63d": 0.12,
                "bench_ret_1d": 0.005, "bench_ret_5d": 0.01,
                "bench_ret_20d": 0.02, "bench_ret_63d": 0.04,
                "alpha_1d": 0.007, "alpha_5d": 0.024,
                "alpha_20d": 0.03, "alpha_63d": 0.08,
                "dir_ret_5d": 0.034, "dir_alpha_5d": 0.024,
            },
        ]
        with csv_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows_data[0].keys()))
            writer.writeheader()
            writer.writerows(rows_data)

        parsed = load_rows(csv_path)
        assert len(parsed) == 1
        r = parsed[0]
        assert r.ticker == "AAPL"
        assert r.triggered_detectors == ["earnings_surprise", "intraday_move"]
        assert "earnings_surprise" in r.triggered_components
        assert r.triggered_components["intraday_move"]["benchmark_used"] == 1.0
        assert r.alpha[5] == pytest.approx(0.024)

    def test_handles_empty_components_gracefully(self, tmp_path):
        csv_path = tmp_path / "no_comps.csv"
        with csv_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "scan_date", "ticker", "rank", "composite_score", "direction",
                "event_severity", "n_detectors_triggered", "triggered_detectors",
                "triggered_components_json", "close_at_scan",
                "ret_1d", "ret_5d", "ret_20d", "ret_63d",
                "bench_ret_1d", "bench_ret_5d", "bench_ret_20d", "bench_ret_63d",
                "alpha_1d", "alpha_5d", "alpha_20d", "alpha_63d",
                "dir_ret_5d", "dir_alpha_5d",
            ])
            writer.writeheader()
            writer.writerow({
                "scan_date": "2024-09-03", "ticker": "AAPL", "rank": 1,
                "composite_score": "75.0", "direction": "neutral",
                "event_severity": "1.0",
                "n_detectors_triggered": "0", "triggered_detectors": "",
                "triggered_components_json": "",
                "close_at_scan": "", "ret_1d": "", "ret_5d": "", "ret_20d": "", "ret_63d": "",
                "bench_ret_1d": "", "bench_ret_5d": "", "bench_ret_20d": "", "bench_ret_63d": "",
                "alpha_1d": "", "alpha_5d": "", "alpha_20d": "", "alpha_63d": "",
                "dir_ret_5d": "", "dir_alpha_5d": "",
            })
        parsed = load_rows(csv_path)
        assert len(parsed) == 1
        assert parsed[0].triggered_components == {}
        assert parsed[0].triggered_detectors == []


# ---------------------------------------------------------------------------
# direction_adjust
# ---------------------------------------------------------------------------


def test_direction_adjust_bullish():
    assert _direction_adjust(0.05, "bullish") == 0.05


def test_direction_adjust_bearish_flips():
    assert _direction_adjust(0.05, "bearish") == -0.05


def test_direction_adjust_none_passes_through():
    assert _direction_adjust(None, "bearish") is None


# ---------------------------------------------------------------------------
# Raw p-value (one-sample t-test against 0)
# ---------------------------------------------------------------------------


class TestRawPvalue:
    def test_returns_none_for_empty(self):
        assert _raw_pvalue([]) is None

    def test_returns_none_for_single_value(self):
        # Can't compute a t-test on n=1; degrees of freedom = 0.
        assert _raw_pvalue([0.05]) is None

    def test_returns_none_for_zero_variance(self):
        # Degenerate sample — t-stat is inf/nan.
        assert _raw_pvalue([0.05, 0.05, 0.05]) is None

    def test_strong_positive_signal_small_pvalue(self):
        # Tightly clustered positive returns — should reject H0: mean=0.
        p = _raw_pvalue([0.04, 0.05, 0.05, 0.06, 0.05])
        assert p is not None
        assert p < 0.001

    def test_noise_around_zero_large_pvalue(self):
        # Symmetric around 0 — should NOT reject H0.
        p = _raw_pvalue([-0.05, -0.02, 0.0, 0.02, 0.05])
        assert p is not None
        assert p > 0.5


# ---------------------------------------------------------------------------
# Benjamini-Hochberg FDR adjustment
# ---------------------------------------------------------------------------


class TestBHAdjust:
    def test_all_none_returns_all_none(self):
        assert _bh_adjust([None, None, None]) == [None, None, None]

    def test_preserves_input_order(self):
        # Output index i must correspond to input index i (BH sorts
        # internally but we re-order back to caller's order).
        p_in = [0.001, 0.50, 0.04, 0.20]
        adj = _bh_adjust(p_in)
        assert len(adj) == 4
        # The smallest raw p stays the smallest after BH.
        smallest_idx = p_in.index(min(p_in))
        assert adj[smallest_idx] == min(adj)

    def test_adjusted_p_monotone_with_raw_p(self):
        # BH is monotone: smaller raw p → smaller (or equal) adjusted p.
        p_in = [0.001, 0.01, 0.05, 0.10, 0.50]
        adj = _bh_adjust(p_in)
        for prev, cur in zip(adj, adj[1:]):
            assert prev <= cur

    def test_keeps_nones_in_place(self):
        adj = _bh_adjust([0.01, None, 0.05, None, 0.001])
        assert adj[1] is None and adj[3] is None
        assert adj[0] is not None and adj[2] is not None and adj[4] is not None

    def test_single_test_adjusted_equals_raw(self):
        # With family of size 1, BH-adjusted == raw.
        adj = _bh_adjust([0.03])
        assert adj == [pytest.approx(0.03)]
