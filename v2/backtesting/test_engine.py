"""Unit tests for v2/backtesting/ — forward returns, trading calendar, engine.

Live integration test is gated by ``BACKTEST_LIVE=1`` env var — skip in
default runs since it makes real network calls and takes minutes.
"""

from __future__ import annotations

import csv
import os
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from v2.backtesting.engine import (
    SKIP_FOR_BACKTEST,
    _build_detector_list,
    _entry_to_row,
    run_backtest,
)
from v2.backtesting.forward_returns import (
    compute_forward_returns,
    direction_adjust,
)
from v2.backtesting.trading_calendar import trading_days_between
from v2.data.models import Price
from v2.scanner.models import ScoredEntry


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_bars(*, start_iso: str, n_days: int, open_close: float = 100.0,
               step: float = 0.0, ticker: str = "X") -> list[Price]:
    """Build N daily bars starting at start_iso, weekdays only, close = open
    + step * i. ``step=0`` → flat series."""
    from datetime import datetime as _dt
    out: list[Price] = []
    d = _dt.strptime(start_iso, "%Y-%m-%d").date()
    i = 0
    while len(out) < n_days:
        if d.weekday() < 5:
            close = open_close + step * i
            out.append(Price(
                open=close, close=close, high=close + 0.1, low=close - 0.1,
                volume=1_000_000, time=d.isoformat(), adjusted_close=close,
            ))
            i += 1
        d += timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# forward_returns
# ---------------------------------------------------------------------------


class TestComputeForwardReturns:
    def test_basic_simple_return(self):
        """5d forward return = (close_5 / close_0) - 1 using adjusted_close."""
        # 10 bars starting 2024-01-02; close = 100, 101, 102, 103, ...
        bars = _make_bars(start_iso="2024-01-02", n_days=10, open_close=100.0, step=1.0)
        fd = MagicMock()
        fd.get_prices.return_value = bars
        out = compute_forward_returns(
            fd, ticker="X", scan_date="2024-01-02",
            windows=(1, 5), benchmark_prices=[],
        )
        # close[0]=100, close[1]=101, close[5]=105
        assert out["close_at_scan"] == pytest.approx(100.0)
        assert out["ret_1d"] == pytest.approx(0.01, rel=1e-6)
        assert out["ret_5d"] == pytest.approx(0.05, rel=1e-6)
        # No benchmark passed → alpha None
        assert out["bench_ret_5d"] is None
        assert out["alpha_5d"] is None

    def test_truncates_when_window_exceeds_data(self):
        """5 bars available, asking for 20d window → ret_20d is None."""
        bars = _make_bars(start_iso="2024-01-02", n_days=5, open_close=100.0)
        fd = MagicMock()
        fd.get_prices.return_value = bars
        out = compute_forward_returns(
            fd, ticker="X", scan_date="2024-01-02",
            windows=(1, 20), benchmark_prices=[],
        )
        assert out["ret_1d"] is not None
        assert out["ret_20d"] is None

    def test_alpha_subtracts_benchmark(self):
        bars = _make_bars(start_iso="2024-01-02", n_days=10, open_close=100.0, step=1.0)
        # Benchmark grows half as fast: close = 100, 100.5, 101, ...
        bench = _make_bars(start_iso="2024-01-02", n_days=10, open_close=100.0, step=0.5)
        fd = MagicMock()
        fd.get_prices.return_value = bars
        out = compute_forward_returns(
            fd, ticker="X", scan_date="2024-01-02",
            windows=(5,), benchmark_prices=bench,
        )
        # ticker ret_5d ≈ 0.05, bench ret_5d ≈ 0.025, alpha ≈ 0.025
        assert out["ret_5d"] == pytest.approx(0.05, rel=1e-6)
        assert out["bench_ret_5d"] == pytest.approx(0.025, rel=1e-6)
        assert out["alpha_5d"] == pytest.approx(0.025, rel=1e-6)

    def test_uses_adjusted_close_for_returns(self):
        """When adjusted_close differs from raw close (ex-div day), use adjusted."""
        bars = _make_bars(start_iso="2024-01-02", n_days=10, open_close=100.0)
        # Day 5: drop raw close 2% (dividend day) but keep adjusted unchanged.
        b5 = bars[5]
        bars[5] = Price(
            open=b5.open, close=b5.close * 0.98,
            high=b5.high, low=b5.low, volume=b5.volume,
            time=b5.time, adjusted_close=b5.close,
        )
        fd = MagicMock()
        fd.get_prices.return_value = bars
        out = compute_forward_returns(
            fd, ticker="X", scan_date="2024-01-02",
            windows=(5,), benchmark_prices=[],
        )
        # adjusted_close stays flat → ret_5d ≈ 0, NOT -2%.
        assert out["ret_5d"] == pytest.approx(0.0, abs=1e-6)

    def test_returns_none_when_no_bars(self):
        fd = MagicMock()
        fd.get_prices.return_value = []
        out = compute_forward_returns(
            fd, ticker="X", scan_date="2024-01-02",
            windows=(5,), benchmark_prices=[],
        )
        assert out["close_at_scan"] is None
        assert out["ret_5d"] is None
        assert out["alpha_5d"] is None


class TestDirectionAdjust:
    def test_bullish_unchanged(self):
        assert direction_adjust(0.05, "bullish") == 0.05
        assert direction_adjust(-0.02, "bullish") == -0.02

    def test_bearish_flipped(self):
        assert direction_adjust(0.05, "bearish") == -0.05
        assert direction_adjust(-0.02, "bearish") == 0.02

    def test_neutral_treated_as_long(self):
        assert direction_adjust(0.05, "neutral") == 0.05

    def test_none_passes_through(self):
        assert direction_adjust(None, "bullish") is None
        assert direction_adjust(None, "bearish") is None


# ---------------------------------------------------------------------------
# trading_calendar
# ---------------------------------------------------------------------------


class TestTradingDaysBetween:
    def test_returns_only_dates_with_bars(self):
        """Bars on weekdays only — weekends naturally excluded."""
        bars = _make_bars(start_iso="2024-01-02", n_days=5)
        fd = MagicMock()
        fd.get_prices.return_value = bars
        days = trading_days_between(
            fd, start_date="2024-01-02", end_date="2024-01-08",
        )
        # 2024-01-02..2024-01-08 spans Mon-Mon — 5 weekdays (Mon Tue Wed Thu Fri)
        # Bars are 2024-01-02 (Tue) through 2024-01-08 (Mon).
        assert len(days) == 5
        assert "2024-01-06" not in days  # Saturday
        assert "2024-01-07" not in days  # Sunday

    def test_empty_when_provider_returns_none(self):
        fd = MagicMock()
        fd.get_prices.return_value = []
        assert trading_days_between(fd, start_date="2024-01-01", end_date="2024-01-31") == []

    def test_respects_inclusive_bounds(self):
        bars = _make_bars(start_iso="2024-01-02", n_days=10)
        fd = MagicMock()
        fd.get_prices.return_value = bars
        days = trading_days_between(
            fd, start_date="2024-01-03", end_date="2024-01-05",
        )
        # In-bounds: 2024-01-03, 04, 05 (all weekdays)
        assert days == ["2024-01-03", "2024-01-04", "2024-01-05"]


# ---------------------------------------------------------------------------
# engine plumbing (without running real scans)
# ---------------------------------------------------------------------------


class TestEnginePlumbing:
    def test_target_price_change_excluded_from_detector_list(self):
        """SKIP_FOR_BACKTEST excludes only target_price_change."""
        det_list = _build_detector_list()
        names = {d.name for d in det_list}
        assert "target_price_change" not in names
        assert "target_price_change" in SKIP_FOR_BACKTEST
        # All other detectors stay in.
        from v2.scanner.detectors import ALL_DETECTORS
        all_names = {c().name for c in ALL_DETECTORS}
        assert names == all_names - {"target_price_change"}

    def test_entry_to_row_flattens_triggers(self):
        """ScoredEntry → CSV-row dict has correct triggered_detectors string
        and direction-adjusted columns."""
        entry = ScoredEntry(
            ticker="AAPL",
            composite_score=88.5,
            direction="bearish",
            event_score=85.0,
            quant_score=None,
            event_severity=3.2,
            rank=1,
            triggers=[
                {"detector": "earnings_surprise", "triggered": True, "severity_z": -3.2,
                 "direction": "bearish", "reason": "", "components": {}, "asof_date": "2024-09-01"},
                {"detector": "insider_cluster", "triggered": False, "severity_z": 0.0,
                 "direction": "neutral", "reason": "", "components": {}, "asof_date": "2024-09-01"},
                {"detector": "intraday_move", "triggered": True, "severity_z": -2.1,
                 "direction": "bearish", "reason": "", "components": {}, "asof_date": "2024-09-01"},
            ],
        )
        fwd = {
            "close_at_scan": 175.0,
            "ret_1d": -0.01, "ret_5d": -0.03, "ret_20d": None, "ret_63d": None,
            "bench_ret_1d": -0.005, "bench_ret_5d": -0.01,
            "bench_ret_20d": None, "bench_ret_63d": None,
            "alpha_1d": -0.005, "alpha_5d": -0.02,
            "alpha_20d": None, "alpha_63d": None,
        }
        row = _entry_to_row(scan_date="2024-09-01", entry=entry, fwd=fwd)
        assert row["triggered_detectors"] == "earnings_surprise|intraday_move"
        assert row["n_detectors_triggered"] == 2
        # bearish entry: dir_ret_5d flips sign of ret_5d
        assert row["dir_ret_5d"] == pytest.approx(0.03)
        assert row["dir_alpha_5d"] == pytest.approx(0.02)
        assert row["composite_score"] == 88.5
        assert row["close_at_scan"] == 175.0
        # components_json: only FIRED detectors, JSON-encoded, compact.
        import json as _json
        comps = _json.loads(row["triggered_components_json"])
        assert set(comps.keys()) == {"earnings_surprise", "intraday_move"}
        # insider_cluster fired = False → not in components dict
        assert "insider_cluster" not in comps


# ---------------------------------------------------------------------------
# Live integration — gated; needs BACKTEST_LIVE=1
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("BACKTEST_LIVE") != "1",
    reason="Live backtest test requires BACKTEST_LIVE=1 env var (hits network)",
)
def test_end_to_end_smoke_3_days_custom_universe(tmp_path):
    """5-ticker × 3-day backtest hitting the real hybrid provider. Verifies
    the CLI path actually produces a valid CSV with sane data."""
    output = tmp_path / "smoke.csv"
    n_rows = run_backtest(
        universe_kind="custom",
        universe_tickers=["AAPL", "MSFT", "NVDA", "AMD", "TSLA"],
        weights_payload={
            "enabled_detectors": ["intraday_move", "bollinger_squeeze"],
        },
        start_date="2024-09-03",
        end_date="2024-09-06",
        top_n=5,
        output_path=output,
        max_days=3,
    )
    assert output.exists()
    assert n_rows >= 0
    with output.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    # Row count matches return value
    assert len(rows) == n_rows
    # Header has the expected columns
    if rows:
        first = rows[0]
        for col in ("scan_date", "ticker", "rank", "composite_score",
                    "ret_5d", "alpha_5d", "dir_alpha_5d"):
            assert col in first
