"""Unit tests for v2/signals — pure-math, mocked DataClient."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from v2.data.models import FinancialMetrics, Price
from v2.signals import (
    EarningsQualitySignal,
    MomentumSignal,
    QualitySignal,
    TechnicalSignal,
    ValueSignal,
)

END_DATE = "2026-05-13"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _price_series(*, n: int = 260, start_close: float = 100.0, daily_drift: float = 0.0) -> list[Price]:
    """Build n trading-day prices ending on END_DATE with a constant daily drift."""
    end = date.fromisoformat(END_DATE)
    bars: list[Price] = []
    cur = end
    series: list[tuple[str, float]] = []
    close = start_close
    # Walk back to find n weekdays.
    while len(series) < n:
        if cur.weekday() < 5:
            series.append((cur.isoformat(), close))
            close = close / (1.0 + daily_drift) if daily_drift != 0 else close
        cur -= timedelta(days=1)
    series.reverse()
    for time_iso, c in series:
        bars.append(
            Price(
                open=c,
                close=c,
                high=c,
                low=c,
                volume=1_000_000,
                time=time_iso,
                adjusted_close=c,
            )
        )
    return bars


def _metrics(**overrides) -> FinancialMetrics:
    defaults = {
        "ticker": "AAPL",
        "report_period": "2026-03-31",
        "period": "ttm",
    }
    defaults.update(overrides)
    return FinancialMetrics(**defaults)


# ---------------------------------------------------------------------------
# MomentumSignal
# ---------------------------------------------------------------------------


class TestMomentumSignal:
    def test_strong_uptrend_is_bullish(self):
        # Daily drift of +0.2% over ~250 days ≈ +65% — strong momentum.
        prices = _price_series(daily_drift=0.002)
        fd = MagicMock()
        fd.get_prices.return_value = prices
        r = MomentumSignal().compute("AAPL", END_DATE, fd)
        assert r.signal_name == "momentum"
        assert r.value > 0.5
        assert r.components["twelve_one_return"] > 0.3

    def test_strong_downtrend_is_bearish(self):
        prices = _price_series(daily_drift=-0.002)
        fd = MagicMock()
        fd.get_prices.return_value = prices
        r = MomentumSignal().compute("AAPL", END_DATE, fd)
        assert r.value < -0.5
        assert r.components["twelve_one_return"] < -0.3

    def test_flat_history_is_neutral(self):
        prices = _price_series(daily_drift=0.0)
        fd = MagicMock()
        fd.get_prices.return_value = prices
        r = MomentumSignal().compute("AAPL", END_DATE, fd)
        assert abs(r.value) < 0.1

    def test_insufficient_data_returns_zero(self):
        fd = MagicMock()
        fd.get_prices.return_value = []
        r = MomentumSignal().compute("AAPL", END_DATE, fd)
        assert r.value == 0.0
        assert "insufficient" in r.metadata.get("reason", "")

    def test_provider_exception_returns_zero(self):
        fd = MagicMock()
        fd.get_prices.side_effect = RuntimeError("boom")
        r = MomentumSignal().compute("AAPL", END_DATE, fd)
        assert r.value == 0.0
        assert "error" in r.metadata


# ---------------------------------------------------------------------------
# ValueSignal
# ---------------------------------------------------------------------------


class TestValueSignal:
    def test_cheap_stock_is_bullish(self):
        fd = MagicMock()
        fd.get_financial_metrics.return_value = [
            _metrics(
                price_to_earnings_ratio=8.0,  # cheap
                price_to_book_ratio=0.9,
                price_to_sales_ratio=0.8,
                free_cash_flow_yield=0.10,  # high yield
            )
        ]
        r = ValueSignal().compute("AAPL", END_DATE, fd)
        assert r.value > 0.5

    def test_expensive_stock_is_bearish(self):
        fd = MagicMock()
        fd.get_financial_metrics.return_value = [
            _metrics(
                price_to_earnings_ratio=40.0,
                price_to_book_ratio=10.0,
                price_to_sales_ratio=12.0,
                free_cash_flow_yield=-0.02,
            )
        ]
        r = ValueSignal().compute("AAPL", END_DATE, fd)
        assert r.value < -0.5

    def test_missing_ratios_returns_zero(self):
        fd = MagicMock()
        fd.get_financial_metrics.return_value = [_metrics()]
        r = ValueSignal().compute("AAPL", END_DATE, fd)
        assert r.value == 0.0
        assert "no valuation" in r.metadata.get("reason", "")

    def test_negative_pe_is_ignored(self):
        """A negative-earnings P/E is uninformative — defer to other factors."""
        fd = MagicMock()
        fd.get_financial_metrics.return_value = [
            _metrics(
                price_to_earnings_ratio=-15.0,
                price_to_book_ratio=2.0,
            )
        ]
        r = ValueSignal().compute("AAPL", END_DATE, fd)
        # PE was skipped; PB=2 is mildly cheap → small positive.
        assert "pe" not in r.components
        assert "pb" in r.components

    def test_no_metrics_returns_zero(self):
        fd = MagicMock()
        fd.get_financial_metrics.return_value = []
        r = ValueSignal().compute("AAPL", END_DATE, fd)
        assert r.value == 0.0


# ---------------------------------------------------------------------------
# QualitySignal
# ---------------------------------------------------------------------------


class TestQualitySignal:
    def test_high_roic_is_bullish(self):
        fd = MagicMock()
        fd.get_financial_metrics.return_value = [
            _metrics(
                return_on_invested_capital=0.25,
                return_on_equity=0.30,
                operating_margin=0.30,
                gross_margin=0.60,
            )
        ]
        r = QualitySignal().compute("AAPL", END_DATE, fd)
        assert r.value > 0.8

    def test_unprofitable_is_bearish(self):
        fd = MagicMock()
        fd.get_financial_metrics.return_value = [
            _metrics(
                return_on_invested_capital=-0.05,
                return_on_equity=-0.10,
                operating_margin=-0.05,
                gross_margin=0.10,
            )
        ]
        r = QualitySignal().compute("AAPL", END_DATE, fd)
        assert r.value < -0.8

    def test_partial_data_uses_present_factors(self):
        fd = MagicMock()
        fd.get_financial_metrics.return_value = [
            _metrics(
                return_on_invested_capital=0.25,
            )
        ]
        r = QualitySignal().compute("AAPL", END_DATE, fd)
        assert r.value > 0
        assert set(r.components) == {"roic"}


# ---------------------------------------------------------------------------
# EarningsQualitySignal
# ---------------------------------------------------------------------------


class TestEarningsQualitySignal:
    def test_strong_growth_is_bullish(self):
        fd = MagicMock()
        fd.get_financial_metrics.return_value = [
            _metrics(
                revenue_growth=0.30,
                earnings_growth=0.50,
                free_cash_flow_growth=0.45,
                earnings_per_share_growth=0.40,
            )
        ]
        r = EarningsQualitySignal().compute("AAPL", END_DATE, fd)
        assert r.value > 0.8

    def test_shrinking_is_bearish(self):
        fd = MagicMock()
        fd.get_financial_metrics.return_value = [
            _metrics(
                revenue_growth=-0.10,
                earnings_growth=-0.30,
                free_cash_flow_growth=-0.40,
                earnings_per_share_growth=-0.20,
            )
        ]
        r = EarningsQualitySignal().compute("AAPL", END_DATE, fd)
        assert r.value < -0.8

    def test_missing_returns_zero(self):
        fd = MagicMock()
        fd.get_financial_metrics.return_value = [_metrics()]
        r = EarningsQualitySignal().compute("AAPL", END_DATE, fd)
        assert r.value == 0.0


# ---------------------------------------------------------------------------
# TechnicalSignal
# ---------------------------------------------------------------------------


class TestTechnicalSignal:
    def test_oversold_uptrend_returns_signal(self):
        # Steady uptrend → RSI mid-high, trend positive.
        prices = _price_series(n=100, daily_drift=0.001)
        fd = MagicMock()
        fd.get_prices.return_value = prices
        r = TechnicalSignal().compute("AAPL", END_DATE, fd)
        assert r.signal_name == "technical"
        assert "rsi" in r.components
        assert "trend_score" in r.components

    def test_downtrend_trend_score_is_negative(self):
        """A monotonic downtrend has trend_score < 0. RSI in monotonic series
        saturates to 0 (oversold = bullish) so the *overall* technical signal
        cancels out — that's intentional in TA, not a bug."""
        prices = _price_series(n=100, daily_drift=-0.001)
        fd = MagicMock()
        fd.get_prices.return_value = prices
        r = TechnicalSignal().compute("AAPL", END_DATE, fd)
        assert r.components["trend_score"] < 0
        assert r.components["ma_dev"] < 0

    def test_insufficient_data_returns_zero(self):
        fd = MagicMock()
        fd.get_prices.return_value = _price_series(n=10)
        r = TechnicalSignal().compute("AAPL", END_DATE, fd)
        assert r.value == 0.0
        assert "insufficient" in r.metadata.get("reason", "")

    def test_value_stays_bounded(self):
        """Even extreme inputs must stay in [-1, +1]."""
        # Massive uptrend.
        prices = _price_series(n=100, daily_drift=0.05)
        fd = MagicMock()
        fd.get_prices.return_value = prices
        r = TechnicalSignal().compute("AAPL", END_DATE, fd)
        assert -1.0 <= r.value <= 1.0


# ---------------------------------------------------------------------------
# Integration: runner wires signals through, composite uses quant
# ---------------------------------------------------------------------------


class TestRunnerIntegration:
    def test_quant_score_is_present_when_signals_provided(self):
        """When any event triggers, signals run and quant_score populates."""
        from v2.scanner.detectors.base import EventDetector, EventTrigger
        from v2.scanner.runner import run_scan

        class _StubDetector(EventDetector):
            name = "stub"

            def detect(self, ticker, end_date, fd, *, ctx=None):
                return EventTrigger(
                    detector="stub",
                    triggered=True,
                    severity_z=2.0,
                    direction="bullish",
                    reason="stub",
                )

        # Stub signal classes that don't need real data.
        from v2.signals.base import BaseSignal
        from v2.models import SignalResult

        class _StubSignal(BaseSignal):
            name = "momentum"  # match a factor_weights key

            def compute(self, ticker, end_date, fd):
                return SignalResult(signal_name=self.name, value=0.8)

        # Quant overlay is OFF by default (quant_weight=0.0); opt into a mix
        # so the composite genuinely blends quant_score in.
        from v2.scanner.models import ScannerWeights

        results = run_scan(
            tickers=["AAA"],
            end_date=END_DATE,
            top_n=10,
            weights=ScannerWeights(event_weight=0.5, quant_weight=0.5),
            detectors=[_StubDetector()],
            quant_signals=[_StubSignal()],
            provider_factory=MagicMock,
        )
        assert len(results) == 1
        entry = results[0]
        assert entry.quant_score is not None
        assert entry.quant_score > 50.0  # value=0.8 → score=90
        # Composite is a mix, not just event_score.
        assert entry.composite_score != entry.event_score

    def test_signal_failure_does_not_kill_ticker(self):
        from v2.scanner.detectors.base import EventDetector, EventTrigger
        from v2.scanner.runner import run_scan
        from v2.signals.base import BaseSignal

        class _StubDetector(EventDetector):
            name = "stub"

            def detect(self, ticker, end_date, fd, *, ctx=None):
                return EventTrigger(
                    detector="stub",
                    triggered=True,
                    severity_z=2.0,
                    direction="bullish",
                    reason="stub",
                )

        class _BoomSignal(BaseSignal):
            name = "momentum"

            def compute(self, ticker, end_date, fd):
                raise RuntimeError("boom")

        results = run_scan(
            tickers=["AAA"],
            end_date=END_DATE,
            top_n=10,
            detectors=[_StubDetector()],
            quant_signals=[_BoomSignal()],
            provider_factory=MagicMock,
        )
        # Ticker still scores (event-only), signal exception was isolated.
        assert len(results) == 1
        assert results[0].quant_score is None
