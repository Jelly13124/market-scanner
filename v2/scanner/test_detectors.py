"""Unit tests for scanner detectors and scoring.

Uses ``unittest.mock.MagicMock`` stubs for FDClient so nothing hits the wire.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from v2.data.models import (
    AnalystAction,
    AnalystTarget,
    CompanyNews,
    EarningsData,
    EarningsRecord,
    InsiderTrade,
    Price,
)
from v2.event_study.filters import filter_retrospective_earnings
from v2.models import SignalResult
from v2.scanner.detectors import (
    EarningsSurpriseDetector,
    InsiderClusterDetector,
    NewsSentimentShiftDetector,
    VolumeAnomalyDetector,
)
from v2.scanner.detectors.base import EventTrigger
from v2.scanner.models import ScannerWeights, ScanContext
from v2.scanner.scoring import compute_composite

END_DATE = "2026-05-13"


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _earnings_record(
    *,
    ticker: str = "AAPL",
    filing_date: str,
    report_period: str,
    source_type: str = "8-K",
    eps: float | None = 1.50,
    estimated_eps: float | None = 1.30,
    eps_surprise: str | None = "BEAT",
) -> EarningsRecord:
    quarterly = None
    if eps_surprise is not None:
        quarterly = EarningsData(
            earnings_per_share=eps,
            estimated_earnings_per_share=estimated_eps,
            eps_surprise=eps_surprise,
        )
    return EarningsRecord(
        ticker=ticker,
        report_period=report_period,
        source_type=source_type,
        filing_date=filing_date,
        quarterly=quarterly,
    )


def _insider(
    *,
    name: str,
    filing_date: str,
    transaction_date: str | None = None,
    value: float = 100_000.0,
    transaction_type: str | None = None,
) -> InsiderTrade:
    return InsiderTrade(
        ticker="AAPL",
        name=name,
        filing_date=filing_date,
        transaction_date=transaction_date or filing_date,
        transaction_value=value,
        transaction_type=transaction_type,
        is_board_director=True,
    )


def _price(time_iso: str, close: float, volume: int = 1_000_000) -> Price:
    return Price(open=close, close=close, high=close, low=close, volume=volume, time=time_iso)


def _flat_prices(*, days: int = 90, close: float = 100.0, vol: int = 1_000_000) -> list[Price]:
    """Build a list of daily Price bars ending on END_DATE."""
    out: list[Price] = []
    end = date.fromisoformat(END_DATE)
    for i in range(days):
        d = end - timedelta(days=days - 1 - i)
        # Skip weekends so the series looks like a real trading calendar.
        if d.weekday() >= 5:
            continue
        out.append(_price(d.isoformat(), close=close, volume=vol))
    return out


def _news_article(
    *,
    sentiment: str | None,
    article_date: str,
    title: str = "headline",
) -> CompanyNews:
    return CompanyNews(
        ticker="AAPL",
        title=title,
        source="test",
        date=article_date,
        sentiment=sentiment,
    )


# ---------------------------------------------------------------------------
# filter_retrospective_earnings — sanity that the extracted util still works
# ---------------------------------------------------------------------------


class TestFilterRetrospective:
    def test_drops_far_filings(self):
        good = _earnings_record(
            filing_date="2026-05-01",
            report_period="2026-03-31",  # 31d gap — kept
        )
        bad = _earnings_record(
            filing_date="2026-05-01",
            report_period="2026-01-15",  # 106d gap — dropped
        )
        out = filter_retrospective_earnings([good, bad])
        assert good in out
        assert bad not in out

    def test_handles_unparseable(self):
        rec = _earnings_record(filing_date="invalid", report_period="2026-01-01")
        assert filter_retrospective_earnings([rec]) == []


# ---------------------------------------------------------------------------
# EarningsSurpriseDetector
# ---------------------------------------------------------------------------


class TestEarningsSurpriseDetector:
    def test_fires_on_fresh_beat(self):
        # Latest filing is 2 days ago — within the 5-biz-day window.
        end = date.fromisoformat(END_DATE)
        latest = _earnings_record(
            filing_date=(end - timedelta(days=2)).isoformat(),
            report_period=(end - timedelta(days=20)).isoformat(),
            eps=2.00, estimated_eps=1.50, eps_surprise="BEAT",
        )
        history = [
            _earnings_record(
                filing_date=(end - timedelta(days=90 + i * 90)).isoformat(),
                report_period=(end - timedelta(days=100 + i * 90)).isoformat(),
                eps=1.0 + i * 0.05, estimated_eps=1.0, eps_surprise="MEET",
            )
            for i in range(4)
        ]
        fd = MagicMock()
        fd.get_earnings_history.return_value = [latest, *history]

        det = EarningsSurpriseDetector()
        trig = det.detect("AAPL", END_DATE, fd)
        assert trig is not None
        assert trig.triggered is True
        assert trig.direction == "bullish"
        assert trig.severity_z > 0
        assert "BEAT" in trig.reason

    def test_fires_on_miss(self):
        end = date.fromisoformat(END_DATE)
        latest = _earnings_record(
            filing_date=(end - timedelta(days=1)).isoformat(),
            report_period=(end - timedelta(days=20)).isoformat(),
            eps=0.80, estimated_eps=1.20, eps_surprise="MISS",
        )
        fd = MagicMock()
        fd.get_earnings_history.return_value = [latest]
        trig = EarningsSurpriseDetector().detect("AAPL", END_DATE, fd)
        assert trig.triggered is True
        assert trig.direction == "bearish"
        assert trig.severity_z < 0

    def test_does_not_fire_when_stale(self):
        end = date.fromisoformat(END_DATE)
        # Latest filing is 30 days ago.
        latest = _earnings_record(
            filing_date=(end - timedelta(days=30)).isoformat(),
            report_period=(end - timedelta(days=40)).isoformat(),
            eps_surprise="BEAT",
        )
        fd = MagicMock()
        fd.get_earnings_history.return_value = [latest]
        trig = EarningsSurpriseDetector().detect("AAPL", END_DATE, fd)
        assert trig is not None
        assert trig.triggered is False

    def test_does_not_fire_on_meet(self):
        end = date.fromisoformat(END_DATE)
        latest = _earnings_record(
            filing_date=(end - timedelta(days=1)).isoformat(),
            report_period=(end - timedelta(days=20)).isoformat(),
            eps_surprise="MEET",
        )
        fd = MagicMock()
        fd.get_earnings_history.return_value = [latest]
        trig = EarningsSurpriseDetector().detect("AAPL", END_DATE, fd)
        assert trig is not None
        assert trig.triggered is False

    def test_returns_none_when_no_data(self):
        fd = MagicMock()
        fd.get_earnings_history.return_value = []
        assert EarningsSurpriseDetector().detect("AAPL", END_DATE, fd) is None

    def test_categorical_floor_applies_when_actuals_missing(self):
        end = date.fromisoformat(END_DATE)
        latest = _earnings_record(
            filing_date=(end - timedelta(days=1)).isoformat(),
            report_period=(end - timedelta(days=20)).isoformat(),
            eps=None, estimated_eps=None, eps_surprise="BEAT",
        )
        fd = MagicMock()
        fd.get_earnings_history.return_value = [latest]
        trig = EarningsSurpriseDetector().detect("AAPL", END_DATE, fd)
        # Severity should fall back to the categorical floor (default 2.0).
        assert trig.triggered is True
        assert abs(trig.severity_z) == pytest.approx(2.0)

    def test_surprise_std_floor_prevents_explosive_z(self):
        """Regression: identical historical surprises collapse std → 0 and
        used to yield |z| in the millions (same pattern as the GEHC insider
        z=+55,257,210,785,000 bug). With the 0.05 std floor, the detector
        falls back to the categorical floor instead.
        """
        end = date.fromisoformat(END_DATE)
        latest = _earnings_record(
            filing_date=(end - timedelta(days=1)).isoformat(),
            report_period=(end - timedelta(days=20)).isoformat(),
            eps=1.02, estimated_eps=1.00, eps_surprise="BEAT",  # tiny 2% beat
        )
        # Four prior quarters with IDENTICAL surprises → std=0.
        history = [
            _earnings_record(
                filing_date=(end - timedelta(days=90 + i * 90)).isoformat(),
                report_period=(end - timedelta(days=100 + i * 90)).isoformat(),
                eps=1.01, estimated_eps=1.00, eps_surprise="BEAT",
            )
            for i in range(4)
        ]
        fd = MagicMock()
        fd.get_earnings_history.return_value = [latest, *history]
        trig = EarningsSurpriseDetector().detect("AAPL", END_DATE, fd)
        assert trig is not None
        assert trig.triggered is True
        # Without the floor, this would be (0.02 - 0.01) / ~0 → astronomical.
        # With the floor, falls back to the categorical floor (2.0).
        assert abs(trig.severity_z) < 5.0
        assert abs(trig.severity_z) == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# InsiderClusterDetector
# ---------------------------------------------------------------------------


class TestInsiderClusterDetector:
    def test_fires_on_cluster_of_buys(self):
        end = date.fromisoformat(END_DATE)
        recent = [
            _insider(name=f"insider_{i}",
                     filing_date=(end - timedelta(days=5 + i)).isoformat(),
                     value=200_000.0)
            for i in range(3)
        ]
        # Some baseline history so the z-score can be computed.
        history = [
            _insider(name=f"old_{i}",
                     filing_date=(end - timedelta(days=60 + i * 30)).isoformat(),
                     value=50_000.0)
            for i in range(8)
        ]
        fd = MagicMock()
        fd.get_insider_trades.return_value = recent + history
        fd.get_market_cap.return_value = 1_000_000_000.0

        trig = InsiderClusterDetector().detect("AAPL", END_DATE, fd)
        assert trig.triggered is True
        assert trig.direction == "bullish"
        assert trig.severity_z > 0

    def test_fires_on_single_big_trade(self):
        end = date.fromisoformat(END_DATE)
        # One huge sell > 1% of $1B market cap.
        big = _insider(
            name="ceo",
            filing_date=(end - timedelta(days=1)).isoformat(),
            value=-50_000_000.0,
        )
        fd = MagicMock()
        fd.get_insider_trades.return_value = [big]
        fd.get_market_cap.return_value = 1_000_000_000.0

        trig = InsiderClusterDetector().detect("AAPL", END_DATE, fd)
        assert trig.triggered is True
        assert trig.direction == "bearish"
        assert trig.severity_z < 0

    def test_does_not_fire_with_one_small_trade(self):
        end = date.fromisoformat(END_DATE)
        one = _insider(
            name="someone",
            filing_date=(end - timedelta(days=1)).isoformat(),
            value=1_000.0,
        )
        fd = MagicMock()
        fd.get_insider_trades.return_value = [one]
        fd.get_market_cap.return_value = 1_000_000_000.0
        trig = InsiderClusterDetector().detect("AAPL", END_DATE, fd)
        assert trig.triggered is False

    def test_returns_none_when_no_trades(self):
        fd = MagicMock()
        fd.get_insider_trades.return_value = []
        assert InsiderClusterDetector().detect("AAPL", END_DATE, fd) is None

    def test_baseline_std_floor_prevents_explosive_z(self):
        """Regression for GEHC z=+55,257,210,785,000.

        M6.b's tightening of insider transaction codes (M/A/D/F → 0 shares)
        means many tickers' historical monthly_grosses are now all-zero
        (option exercises, grants, tax withholding). Without a std floor,
        that collapses std → 0 and z explodes by ~14 orders of magnitude.
        """
        end = date.fromisoformat(END_DATE)
        # Cluster trigger: 3 distinct buyers in recent window (14d default).
        recent = [
            _insider(name=f"buyer_{i}",
                     filing_date=(end - timedelta(days=5 + i)).isoformat(),
                     value=200_000.0)
            for i in range(3)
        ]
        # History: all-zero monthly grosses (e.g. only M-coded option
        # exercises in the trailing year, now mapping to 0 shares).
        history = [
            _insider(name=f"old_{i}",
                     filing_date=(end - timedelta(days=60 + i * 30)).isoformat(),
                     value=0.0)
            for i in range(8)
        ]
        fd = MagicMock()
        fd.get_insider_trades.return_value = recent + history
        fd.get_market_cap.return_value = 1_000_000_000.0

        trig = InsiderClusterDetector().detect("AAPL", END_DATE, fd)
        assert trig is not None
        assert trig.triggered is True
        # Without the floor, this would be (600k - 0) / ~0 → astronomical.
        # With the floor, falls back to the cluster categorical magnitude 2.5,
        # then multiplied by the buy-side multiplier (1.3) → 3.25.
        assert abs(trig.severity_z) < 5.0
        assert abs(trig.severity_z) == pytest.approx(2.5 * 1.3)


class TestInsiderAsymmetric:
    """Asymmetric thresholds + severity mults per task_plan_scanner_v2 §3.2.

    Reflects Cohen-Malloy-Pomorski 2012: insider BUYS carry strong information
    content; insider SELLS are weaker (diversification, taxes, 10b5-1 plans)."""

    def _history(self, *, days_ago: int = 60, n: int = 8, value: float = 50_000.0):
        """Background insider history outside the cluster window so the
        recent-window cluster is the only thing in play."""
        end = date.fromisoformat(END_DATE)
        return [
            _insider(
                name=f"old_{i}",
                filing_date=(end - timedelta(days=days_ago + i * 30)).isoformat(),
                value=value,
            )
            for i in range(n)
        ]

    def test_three_buyers_is_enough_to_cluster_fire(self):
        """Bullish gate is 3 insiders (raised from 2 on 2026-05-21 after
        backtest showed insider_cluster 5d alpha = −2.52% FDR-significant
        at the old 2-buyer threshold). Cohen-Malloy-Pomorski's "even small
        clusters are meaningful" still holds, but at 2 the marginal trigger
        is FDR-significant noise."""
        end = date.fromisoformat(END_DATE)
        recent = [
            _insider(name=f"buyer_{i}",
                     filing_date=(end - timedelta(days=5 + i)).isoformat(),
                     value=300_000.0)
            for i in range(3)
        ]
        fd = MagicMock()
        fd.get_insider_trades.return_value = recent + self._history()
        fd.get_market_cap.return_value = 1_000_000_000.0
        trig = InsiderClusterDetector().detect("AAPL", END_DATE, fd)
        assert trig.triggered is True
        assert trig.direction == "bullish"

    def test_two_buyers_does_NOT_cluster_fire(self):
        """Verify the 2 → 3 threshold bump: 2 buyers at $300k each (under
        the new $500k single-buy threshold) should no longer trigger."""
        end = date.fromisoformat(END_DATE)
        recent = [
            _insider(name=f"buyer_{i}",
                     filing_date=(end - timedelta(days=5 + i)).isoformat(),
                     value=300_000.0)
            for i in range(2)
        ]
        fd = MagicMock()
        fd.get_insider_trades.return_value = recent + self._history()
        fd.get_market_cap.return_value = 1_000_000_000.0
        trig = InsiderClusterDetector().detect("AAPL", END_DATE, fd)
        # Cluster gate fails (2 < 3); single-buy gate also fails (max $300k < $500k)
        assert trig.triggered is False

    def test_three_sellers_does_NOT_cluster_fire(self):
        """Bearish gate is 4 sellers — 3 is below threshold. This is the
        feature that cuts the sell-side noise we observed in production
        (~10/20 of pre-refactor watchlist was 3-seller bearish noise)."""
        end = date.fromisoformat(END_DATE)
        recent = [
            _insider(name=f"seller_{i}",
                     filing_date=(end - timedelta(days=5 + i)).isoformat(),
                     value=-200_000.0)
            for i in range(3)
        ]
        fd = MagicMock()
        fd.get_insider_trades.return_value = recent + self._history()
        fd.get_market_cap.return_value = 1_000_000_000.0
        trig = InsiderClusterDetector().detect("AAPL", END_DATE, fd)
        # cluster gate fails (3 < 4); single-sell gate also fails ($200k < 1% of $1B = $10M)
        assert trig.triggered is False

    def test_four_sellers_cluster_fires_bearish(self):
        end = date.fromisoformat(END_DATE)
        recent = [
            _insider(name=f"seller_{i}",
                     filing_date=(end - timedelta(days=5 + i)).isoformat(),
                     value=-200_000.0)
            for i in range(4)
        ]
        fd = MagicMock()
        fd.get_insider_trades.return_value = recent + self._history()
        fd.get_market_cap.return_value = 1_000_000_000.0
        trig = InsiderClusterDetector().detect("AAPL", END_DATE, fd)
        assert trig.triggered is True
        assert trig.direction == "bearish"

    def test_buy_severity_higher_than_sell_at_same_z(self):
        """Same z-score gets a larger composite contribution on the buy side
        (× 1.3) than on the sell side (× 0.7). With std-floor falling back
        to z=2.5 categorical, buy → 3.25, sell → 1.75.

        Uses 3 buyers (current default min) and 4 sellers so both gates
        fire on their respective sides; the test isolates the multiplier
        math, not the cluster-size threshold."""
        end = date.fromisoformat(END_DATE)
        # 3 buyers — buy cluster fires categorical magnitude 2.5
        buy_recent = [
            _insider(name=f"buyer_{i}",
                     filing_date=(end - timedelta(days=5 + i)).isoformat(),
                     value=300_000.0)
            for i in range(3)
        ]
        # 4 sellers — sell cluster fires categorical magnitude 2.5
        sell_recent = [
            _insider(name=f"seller_{i}",
                     filing_date=(end - timedelta(days=5 + i)).isoformat(),
                     value=-300_000.0)
            for i in range(4)
        ]
        # All-zero history → std floor kicks in → categorical 2.5 fallback
        history = [
            _insider(name=f"old_{i}",
                     filing_date=(end - timedelta(days=60 + i * 30)).isoformat(),
                     value=0.0)
            for i in range(8)
        ]
        fd_buy = MagicMock()
        fd_buy.get_insider_trades.return_value = buy_recent + history
        fd_buy.get_market_cap.return_value = 1_000_000_000.0
        fd_sell = MagicMock()
        fd_sell.get_insider_trades.return_value = sell_recent + history
        fd_sell.get_market_cap.return_value = 1_000_000_000.0
        buy = InsiderClusterDetector().detect("AAPL", END_DATE, fd_buy)
        sell = InsiderClusterDetector().detect("AAPL", END_DATE, fd_sell)
        assert buy.severity_z == pytest.approx(2.5 * 1.3)    # +3.25
        assert sell.severity_z == pytest.approx(-2.5 * 0.7)  # -1.75
        # Buy severity in absolute terms is ~1.86x sell severity (1.3/0.7).
        assert abs(buy.severity_z) > abs(sell.severity_z)

    def test_single_buy_requires_p_transaction_code(self):
        """A single $1M buy ONLY fires the single-buy path when transaction_type='P'
        (open-market purchase). Stock awards (A), option exercises (M),
        gifts (G), withholding (F) all map to v>0 but don't qualify."""
        end = date.fromisoformat(END_DATE)
        # Single huge buy, but NOT 'P' code — should NOT trigger single-buy path
        recent_award = [
            _insider(name="solo", filing_date=END_DATE,
                     value=1_000_000.0, transaction_type="A"),  # stock award
        ]
        fd = MagicMock()
        fd.get_insider_trades.return_value = recent_award + self._history()
        fd.get_market_cap.return_value = 1_000_000_000.0
        # 1 buyer < min_buyers=3 → cluster gate fails; A-code disqualifies single-buy
        trig = InsiderClusterDetector().detect("AAPL", END_DATE, fd)
        assert trig.triggered is False

        # Same trade but transaction_type='P' (open-market) → fires
        recent_p = [
            _insider(name="solo", filing_date=END_DATE,
                     value=1_000_000.0, transaction_type="P"),
        ]
        fd2 = MagicMock()
        fd2.get_insider_trades.return_value = recent_p + self._history()
        fd2.get_market_cap.return_value = 1_000_000_000.0
        trig2 = InsiderClusterDetector().detect("AAPL", END_DATE, fd2)
        assert trig2.triggered is True
        assert trig2.direction == "bullish"
        assert trig2.components["direction_path_single_buy"] == 1.0

    def test_severity_capped_at_5(self):
        """Regression for ADBE 2026-05-16: gross=$11M vs mu=$50k baseline,
        sigma=$100k → z=-110. Without cap that severity flows into composite
        ranking and dominates everything else. After cap, |severity| ≤ 5."""
        end = date.fromisoformat(END_DATE)
        # Recent: 4 sellers each $5M → cluster fires bearish, gross = $20M
        recent = [
            _insider(name=f"seller_{i}",
                     filing_date=(end - timedelta(days=5 + i)).isoformat(),
                     value=-5_000_000.0)
            for i in range(4)
        ]
        # History: 12 months with VARYING activity so monthly std is meaningful
        # (avoids the std-floor categorical-2.5 fallback). Each month gets
        # a different per-trade value cycling through 50k/100k/150k/200k.
        # Buckets: ~$50k, $100k, $150k, $200k (3 of each) → mu ≈ $125k,
        # sigma ≈ $55k (well above mu*0.10 = $12.5k floor).
        # z = ($20M - $125k) / $55k ≈ 361 → severity_mag = 361 × 0.7 = ~253
        # without cap. Cap clips to 5.0 → severity = -5.0.
        history = [
            _insider(name=f"old_{i}",
                     filing_date=(end - timedelta(days=30 + i * 30)).isoformat(),
                     value=50_000.0 * (1 + (i % 4)))
            for i in range(12)
        ]
        fd = MagicMock()
        fd.get_insider_trades.return_value = recent + history
        fd.get_market_cap.return_value = 1_000_000_000.0
        trig = InsiderClusterDetector().detect("AAPL", END_DATE, fd)
        assert trig.triggered is True
        assert abs(trig.severity_z) <= 5.0, (
            f"severity uncapped: {trig.severity_z}; "
            f"raw_z={trig.components.get('raw_z')}"
        )
        # Confirm the cap actually fired (otherwise the test isn't proving anything)
        assert trig.components["severity_capped"] == 1.0
        # Bearish direction → severity should be exactly -5.0 after cap.
        assert trig.severity_z == pytest.approx(-5.0)


# ---------------------------------------------------------------------------
# PriceVolumeAnomalyDetector
# ---------------------------------------------------------------------------


def _build_history_with_spike(spike_pct: float, spike_volume_mult: float = 1.0):
    """Build a flat history with a single big move on the last day."""
    end = date.fromisoformat(END_DATE)
    prices: list[Price] = []
    base_close = 100.0
    days = []
    d = end - timedelta(days=90)
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    for i, dy in enumerate(days):
        # Small noise to give the std a positive value.
        close = base_close + 0.05 * ((i % 7) - 3)
        prices.append(_price(dy.isoformat(), close=close, volume=1_000_000))
    # Replace last bar.
    prev_close = prices[-2].close
    new_close = prev_close * (1.0 + spike_pct)
    prices[-1] = _price(
        days[-1].isoformat(), close=new_close, volume=int(1_000_000 * spike_volume_mult)
    )
    return prices


class TestVolumeAnomalyDetector:
    def test_fires_on_volume_spike_with_calm_return(self):
        # +0.1% return (well under 1.5% anti-gate), 20x volume → fires bullish
        prices = _build_history_with_spike(spike_pct=0.001, spike_volume_mult=20.0)
        fd = MagicMock()
        fd.get_prices.return_value = prices
        trig = VolumeAnomalyDetector().detect("AAPL", END_DATE, fd)
        assert trig.triggered is True
        assert trig.direction == "bullish"
        assert trig.severity_z > 0
        assert "flat day" in trig.reason

    def test_fires_bearish_on_volume_spike_with_small_negative_return(self):
        prices = _build_history_with_spike(spike_pct=-0.008, spike_volume_mult=20.0)
        fd = MagicMock()
        fd.get_prices.return_value = prices
        trig = VolumeAnomalyDetector().detect("AAPL", END_DATE, fd)
        assert trig.triggered is True
        assert trig.direction == "bearish"
        assert trig.severity_z < 0

    def test_does_not_fire_on_big_return_alone(self):
        # +10% return without volume spike → return-only signal is IDAY's job now
        prices = _build_history_with_spike(spike_pct=0.10, spike_volume_mult=1.0)
        fd = MagicMock()
        fd.get_prices.return_value = prices
        trig = VolumeAnomalyDetector().detect("AAPL", END_DATE, fd)
        # No volume spike → vol_hit is False → triggered=False
        assert trig.triggered is False

    def test_anti_gate_blocks_volume_spike_with_big_return(self):
        # 20x volume but with a -5% return → IDAY territory, VOL stays out
        prices = _build_history_with_spike(spike_pct=-0.05, spike_volume_mult=20.0)
        fd = MagicMock()
        fd.get_prices.return_value = prices
        trig = VolumeAnomalyDetector().detect("AAPL", END_DATE, fd)
        assert trig.triggered is False
        assert "IDAY territory" in trig.reason

    def test_does_not_fire_on_flat(self):
        prices = _build_history_with_spike(spike_pct=0.002, spike_volume_mult=1.0)
        fd = MagicMock()
        fd.get_prices.return_value = prices
        trig = VolumeAnomalyDetector().detect("AAPL", END_DATE, fd)
        assert trig is None or trig.triggered is False

    def test_returns_none_when_not_enough_history(self):
        fd = MagicMock()
        fd.get_prices.return_value = [_price("2026-05-13", 100)]
        assert VolumeAnomalyDetector().detect("AAPL", END_DATE, fd) is None

    def test_prefers_adjusted_close_when_available(self):
        """Anti-gate uses adjusted_close so a 2% dividend day isn't mistaken for a
        2% move that knocks out the gate."""
        end = date.fromisoformat(END_DATE)
        days: list[date] = []
        d = end - timedelta(days=90)
        while d <= end:
            if d.weekday() < 5:
                days.append(d)
            d += timedelta(days=1)
        prices: list[Price] = []
        for i, dy in enumerate(days):
            base = 100.0 + 0.05 * ((i % 7) - 3)
            prices.append(Price(
                open=base, close=base, high=base, low=base,
                volume=1_000_000, time=dy.isoformat(),
                adjusted_close=base,
            ))
        # Last bar: raw close drops 2%, adjusted_close unchanged (dividend); 20x volume.
        last = prices[-1]
        prices[-1] = Price(
            open=last.open,
            close=last.close * 0.98,
            high=last.high, low=last.low,
            volume=last.volume * 20, time=last.time,
            adjusted_close=last.close,                # actually flat
        )
        fd = MagicMock()
        fd.get_prices.return_value = prices
        trig = VolumeAnomalyDetector().detect("AAPL", END_DATE, fd)
        # Adjusted-close return is ~0 → anti-gate passes → fires on volume spike.
        assert trig.triggered is True

    def test_volume_std_floor_prevents_explosive_z(self):
        """Regression: ultra-stable trailing volume used to give z in the hundreds.

        With the 10%-of-mean floor, a 5x volume move is bounded.
        """
        end = date.fromisoformat(END_DATE)
        days: list[date] = []
        d = end - timedelta(days=90)
        while d <= end:
            if d.weekday() < 5:
                days.append(d)
            d += timedelta(days=1)
        prices: list[Price] = []
        for i, dy in enumerate(days):
            # Identical volumes every day → trailing std = 0 without floor.
            prices.append(Price(
                open=100.0, close=100.0, high=100.0, low=100.0,
                volume=1_000_000, time=dy.isoformat(),
                adjusted_close=100.0,
            ))
        # Last bar: 5x volume, flat price (anti-gate passes)
        prices[-1] = Price(
            open=100.0, close=100.0, high=100.0, low=100.0,
            volume=5_000_000, time=days[-1].isoformat(),
            adjusted_close=100.0,
        )
        fd = MagicMock()
        fd.get_prices.return_value = prices
        trig = VolumeAnomalyDetector().detect("AAPL", END_DATE, fd)
        assert trig is not None
        # 5x mean / 10%-of-mean floor = z=40. Floor keeps it bounded; without
        # floor it would blow up to thousands.
        assert abs(trig.components["z_volume"]) < 100.0


# ---------------------------------------------------------------------------
# IntradayMoveDetector
# ---------------------------------------------------------------------------


def _build_ohlc_history(*, days: int = 80, base: float = 100.0, jitter: float = 0.5):
    """Build a quiet OHLC history with small daily moves — gives a non-zero std
    floor without dominating any sub-signal."""
    from v2.data.models import Price
    end = date.fromisoformat(END_DATE)
    out: list[Price] = []
    d = end - timedelta(days=days + 30)
    while len(out) < days and d <= end:
        if d.weekday() < 5:
            # Tiny zigzag — open ≈ prev close, range ≈ 0.5%, no gap.
            open_ = base + jitter * ((len(out) % 5) - 2)
            close_ = open_ + jitter * 0.5
            high_ = max(open_, close_) + jitter * 0.3
            low_ = min(open_, close_) - jitter * 0.3
            out.append(Price(open=open_, close=close_, high=high_, low=low_,
                             volume=1_000_000, time=d.isoformat()))
        d += timedelta(days=1)
    return out


class TestIntradayMoveDetector:
    def test_fires_on_big_gap_up(self):
        from v2.data.models import Price
        from v2.scanner.detectors import IntradayMoveDetector

        history = _build_ohlc_history(days=80, base=100.0, jitter=0.3)
        # Today: open jumps 5% over prev close, flat through the day.
        end = date.fromisoformat(END_DATE)
        last_prev = history[-1].close
        today = Price(
            open=last_prev * 1.05, close=last_prev * 1.05,
            high=last_prev * 1.05, low=last_prev * 1.05,
            volume=1_000_000, time=end.isoformat(),
        )
        fd = MagicMock()
        fd.get_prices.return_value = history + [today]
        trig = IntradayMoveDetector().detect("AAPL", END_DATE, fd)
        assert trig is not None
        assert trig.triggered is True
        # gap dominates; close==open so cvo=0 → direction neutral (no cvo sign).
        assert "gap" in trig.reason
        assert trig.components["gap"] > 0.04

    def test_fires_on_intraday_drop(self):
        from v2.data.models import Price
        from v2.scanner.detectors import IntradayMoveDetector

        history = _build_ohlc_history(days=80)
        end = date.fromisoformat(END_DATE)
        prev = history[-1].close
        # Open flat, close down 5% — pure intraday selloff.
        today = Price(
            open=prev, close=prev * 0.95,
            high=prev * 1.001, low=prev * 0.94,
            volume=1_000_000, time=end.isoformat(),
        )
        fd = MagicMock()
        fd.get_prices.return_value = history + [today]
        trig = IntradayMoveDetector().detect("AAPL", END_DATE, fd)
        assert trig.triggered is True
        assert trig.direction == "bearish"
        assert trig.severity_z < 0
        assert "cvo" in trig.reason

    def test_fires_on_wide_range_only(self):
        from v2.data.models import Price
        from v2.scanner.detectors import IntradayMoveDetector

        history = _build_ohlc_history(days=80)
        end = date.fromisoformat(END_DATE)
        prev = history[-1].close
        # Open == prev close (no gap), close == open (no cvo), but 8% range.
        today = Price(
            open=prev, close=prev,
            high=prev * 1.04, low=prev * 0.96,
            volume=1_000_000, time=end.isoformat(),
        )
        fd = MagicMock()
        fd.get_prices.return_value = history + [today]
        trig = IntradayMoveDetector().detect("AAPL", END_DATE, fd)
        assert trig.triggered is True
        # Range-only → direction neutral.
        assert trig.direction == "neutral"
        assert "range" in trig.reason

    def test_does_not_fire_on_quiet_day(self):
        from v2.data.models import Price
        from v2.scanner.detectors import IntradayMoveDetector

        history = _build_ohlc_history(days=80)
        end = date.fromisoformat(END_DATE)
        prev = history[-1].close
        # Today looks like every other day.
        today = Price(
            open=prev, close=prev * 1.002,
            high=prev * 1.003, low=prev * 0.999,
            volume=1_000_000, time=end.isoformat(),
        )
        fd = MagicMock()
        fd.get_prices.return_value = history + [today]
        trig = IntradayMoveDetector().detect("AAPL", END_DATE, fd)
        assert trig is not None
        assert trig.triggered is False

    def test_returns_none_when_insufficient_history(self):
        from v2.scanner.detectors import IntradayMoveDetector
        fd = MagicMock()
        fd.get_prices.return_value = _build_ohlc_history(days=20)
        assert IntradayMoveDetector().detect("AAPL", END_DATE, fd) is None

    def test_returns_none_when_today_open_missing(self):
        from v2.data.models import Price
        from v2.scanner.detectors import IntradayMoveDetector

        history = _build_ohlc_history(days=80)
        end = date.fromisoformat(END_DATE)
        # Today's open is 0 — undefined return basis. Skip cleanly.
        today = Price(
            open=0.0, close=100.0, high=101.0, low=99.0,
            volume=1_000_000, time=end.isoformat(),
        )
        fd = MagicMock()
        fd.get_prices.return_value = history + [today]
        assert IntradayMoveDetector().detect("AAPL", END_DATE, fd) is None

    def test_z_range_demeaned_so_normal_range_does_not_fire(self):
        """Regression for 2026-05-16 production bug: ``z_rng = rng / rng_std``
        (no demean) made every stock with a typical positive range fire,
        because the "z-score" was actually a ratio of magnitude to spread
        (range is strictly positive so its mean is nontrivial).

        Setup: 80 bars with a stable 2% range; today also has 2% range —
        completely normal day for this stock. Properly demeaned z should
        be ≈ 0; the old broken formula gave z ≈ 4 and tripped the gate.
        """
        from v2.data.models import Price
        from v2.scanner.detectors import IntradayMoveDetector
        end = date.fromisoformat(END_DATE)
        history: list[Price] = []
        d = end - timedelta(days=100)
        while len(history) < 80 and d <= end:
            if d.weekday() < 5:
                # Every bar has a 2% range (high = open*1.01, low = open*0.99)
                # and close = open (no cvo, no gap signal).
                history.append(Price(
                    open=100.0, close=100.0,
                    high=101.0, low=99.0,
                    volume=1_000_000, time=d.isoformat(),
                ))
            d += timedelta(days=1)
        # Today: identical 2% range. Demeaned z_rng ≈ 0; non-demeaned would
        # be ~4 and would fire the gate.
        today = Price(
            open=100.0, close=100.0, high=101.0, low=99.0,
            volume=1_000_000, time=end.isoformat(),
        )
        fd = MagicMock()
        fd.get_prices.return_value = history + [today]
        trig = IntradayMoveDetector().detect("AAPL", END_DATE, fd)
        assert trig is not None
        assert trig.triggered is False, (
            f"normal-range day must NOT fire range gate; got severity={trig.severity_z}, "
            f"z_range={trig.components.get('z_range')}"
        )
        # Specifically guard against z_rng being interpreted as magnitude:
        assert abs(trig.components["z_range"]) < 1.0, (
            "z_range must be properly demeaned around zero — old broken "
            "formula z = today/std gave non-zero z on normal-range days"
        )


class TestIntradayMoveDetectorBenchmark:
    """SPY/QQQ-relative adjustment via ScanContext.benchmark_prices."""

    def _det(self):
        """Detector instance with high range thresholds so the cvo/gap tests
        below aren't muddied by range firing on synthetic-flat baselines."""
        from v2.scanner.detectors import IntradayMoveDetector
        return IntradayMoveDetector(z_threshold=10.0, range_pct=0.20)

    def _build_today_pair(self, *, ticker_cvo: float, spy_cvo: float):
        """Return (ticker_history+today, spy_history+today) sharing the same dates.
        Both have an 80-day baseline with realistic ~1% daily volatility; today's
        close_vs_open is set per-arg. ``range`` stays raw — when both cvo args
        are large (e.g. ±3%), range will fire even after benchmark neutralizes
        cvo, which is the intended behavior, so tests using this fixture should
        keep |cvo| modest enough that range stays below threshold."""
        from v2.data.models import Price
        end = date.fromisoformat(END_DATE)
        # Use jitter=1.5 to get baseline cvo std around 1% — closer to real
        # market vol than the default 0.3.
        ticker_history = _build_ohlc_history(days=80, base=100.0, jitter=1.5)
        ticker_history = [b for b in ticker_history if b.time[:10] != END_DATE]
        spy_history = _build_ohlc_history(days=80, base=400.0, jitter=2.0)
        spy_history = [b for b in spy_history if b.time[:10] != END_DATE]
        # Force matching time stamps so the date dict lookup aligns.
        spy_history = [
            Price(open=s.open, close=s.close, high=s.high, low=s.low,
                  volume=s.volume, time=t.time)
            for s, t in zip(spy_history, ticker_history)
        ]
        prev_t = ticker_history[-1].close
        prev_s = spy_history[-1].close
        ticker_today = Price(
            open=prev_t, close=prev_t * (1.0 + ticker_cvo),
            high=max(prev_t, prev_t * (1.0 + ticker_cvo)),
            low=min(prev_t, prev_t * (1.0 + ticker_cvo)),
            volume=1_000_000, time=end.isoformat(),
        )
        spy_today = Price(
            open=prev_s, close=prev_s * (1.0 + spy_cvo),
            high=max(prev_s, prev_s * (1.0 + spy_cvo)),
            low=min(prev_s, prev_s * (1.0 + spy_cvo)),
            volume=10_000_000, time=end.isoformat(),
        )
        return ticker_history + [ticker_today], spy_history + [spy_today]

    def test_no_benchmark_uses_raw_values(self):
        """Without ctx.benchmark_prices, behavior is unchanged from before."""
        from v2.scanner.detectors import IntradayMoveDetector
        ticker_prices, _ = self._build_today_pair(ticker_cvo=-0.05, spy_cvo=0.0)
        fd = MagicMock()
        fd.get_prices.return_value = ticker_prices
        trig = IntradayMoveDetector().detect("AAPL", END_DATE, fd, ctx=None)
        assert trig.triggered is True
        assert trig.components["benchmark_used"] == 0.0
        # adjusted_cvo equals raw_cvo when no benchmark
        assert trig.components["adjusted_cvo"] == trig.components["raw_cvo"]

    def test_benchmark_neutralizes_market_move(self):
        """Stock cvo = -1.5% on SPY cvo = -1.5% → adjusted ≈ 0 → does NOT fire.
        (cvo magnitude kept modest so range — which stays raw — doesn't trigger.)"""
        from v2.scanner.detectors import IntradayMoveDetector
        ticker_prices, spy_prices = self._build_today_pair(
            ticker_cvo=-0.015, spy_cvo=-0.015,
        )
        fd = MagicMock()
        fd.get_prices.return_value = ticker_prices
        ctx = ScanContext(ticker="AAPL", end_date=END_DATE, benchmark_prices=spy_prices)
        trig = self._det().detect("AAPL", END_DATE, fd, ctx=ctx)
        assert trig is not None
        assert trig.triggered is False
        assert trig.components["benchmark_used"] == 1.0
        # adjusted_cvo ≈ 0; raw_cvo ≈ -0.015
        assert abs(trig.components["adjusted_cvo"]) < 0.003
        assert trig.components["raw_cvo"] < -0.012

    def test_benchmark_amplifies_idiosyncratic_move(self):
        """Stock cvo = -5% on SPY cvo = +1% → adjusted ≈ -6% → fires bearish."""
        from v2.scanner.detectors import IntradayMoveDetector
        ticker_prices, spy_prices = self._build_today_pair(
            ticker_cvo=-0.05, spy_cvo=0.01,
        )
        fd = MagicMock()
        fd.get_prices.return_value = ticker_prices
        ctx = ScanContext(ticker="AAPL", end_date=END_DATE, benchmark_prices=spy_prices)
        trig = self._det().detect("AAPL", END_DATE, fd, ctx=ctx)
        assert trig.triggered is True
        assert trig.direction == "bearish"
        assert trig.components["benchmark_used"] == 1.0
        # Adjusted is more extreme than raw (move and benchmark moved opposite)
        assert trig.components["adjusted_cvo"] < trig.components["raw_cvo"]

    def test_benchmark_with_missing_dates_silent_fallback(self):
        """When benchmark series doesn't cover the ticker dates, bench lookups
        return (0, 0) silently → adjusted == raw, no crash."""
        from v2.data.models import Price
        from v2.scanner.detectors import IntradayMoveDetector
        ticker_prices, _ = self._build_today_pair(ticker_cvo=-0.05, spy_cvo=0.0)
        # Benchmark has bars but with completely different dates (year ago).
        wrong_date_spy = [
            Price(open=400.0, close=400.0, high=401.0, low=399.0,
                  volume=10_000_000, time="2024-01-15"),
        ]
        fd = MagicMock()
        fd.get_prices.return_value = ticker_prices
        ctx = ScanContext(ticker="AAPL", end_date=END_DATE, benchmark_prices=wrong_date_spy)
        trig = self._det().detect("AAPL", END_DATE, fd, ctx=ctx)
        # use_adjusted is True (benchmark dict non-empty), but per-day lookups
        # all miss → bench_cvo/gap = 0 → adjusted == raw. Detector still fires.
        assert trig is not None
        assert trig.triggered is True
        # spy_cvo / spy_gap should be 0 (date lookup missed)
        assert trig.components["spy_cvo"] == 0.0


# ---------------------------------------------------------------------------
# MultiHorizonBreakoutDetector — REMOVED 2026-05-19.
# The detector was deleted because v2/signals/technical already produces
# 52-week-high / momentum signals from the same underlying price data;
# keeping the event-style detector alongside the quant signal produced
# duplicate alpha attribution. Tests + helpers removed with the detector.
# Historical backtest_*.csv files at the repo root still contain
# breakout_52w trigger entries; v2/backtesting/analyze.py's
# _break_horizons_for() and report_break_horizon_split() are intentionally
# kept so those CSVs remain analyzable.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# NewsSentimentShiftDetector
# ---------------------------------------------------------------------------


class TestNewsSentimentShiftDetector:
    def test_fires_on_positive_shift(self):
        end = date.fromisoformat(END_DATE)
        # Baseline: 20 articles, mostly neutral with a couple negative.
        baseline = []
        for i in range(20):
            sentiment = "neutral" if i < 18 else "negative"
            d = (end - timedelta(days=30 + i)).isoformat()
            baseline.append(_news_article(sentiment=sentiment, article_date=d))
        # Recent: 5 positive in the last 7 days.
        recent = [
            _news_article(sentiment="positive",
                          article_date=(end - timedelta(days=i)).isoformat())
            for i in range(5)
        ]
        fd = MagicMock()
        fd.get_news.return_value = baseline + recent

        trig = NewsSentimentShiftDetector().detect("AAPL", END_DATE, fd)
        assert trig.triggered is True
        assert trig.direction == "bullish"
        assert trig.severity_z > 0

    def test_does_not_fire_when_recent_articles_below_threshold(self):
        end = date.fromisoformat(END_DATE)
        baseline = [
            _news_article(sentiment="neutral",
                          article_date=(end - timedelta(days=30 + i)).isoformat())
            for i in range(20)
        ]
        # Only 1 recent article.
        recent = [_news_article(sentiment="positive",
                                article_date=(end - timedelta(days=1)).isoformat())]
        fd = MagicMock()
        fd.get_news.return_value = baseline + recent
        trig = NewsSentimentShiftDetector().detect("AAPL", END_DATE, fd)
        assert trig.triggered is False

    def test_baseline_std_floor_prevents_explosive_z(self):
        """Regression: homogeneous baseline (all-neutral) used to yield z=±333,333.

        With the 0.10 std floor in place, |z| stays in a sane range.
        """
        end = date.fromisoformat(END_DATE)
        baseline = [
            _news_article(sentiment="neutral",
                          article_date=(end - timedelta(days=30 + i)).isoformat())
            for i in range(30)
        ]
        recent = [
            _news_article(sentiment="positive",
                          article_date=(end - timedelta(days=i)).isoformat())
            for i in range(5)
        ]
        fd = MagicMock()
        fd.get_news.return_value = baseline + recent
        trig = NewsSentimentShiftDetector().detect("AAPL", END_DATE, fd)
        assert trig is not None
        assert trig.triggered is True
        # With std floor 0.10 and mean shift 1.0, z = 10 — not 1,000,000.
        assert abs(trig.severity_z) < 20.0
        assert trig.severity_z > 0

    def test_returns_none_when_no_news(self):
        fd = MagicMock()
        fd.get_news.return_value = []
        assert NewsSentimentShiftDetector().detect("AAPL", END_DATE, fd) is None


# ---------------------------------------------------------------------------
# AnalystRatingDetector
# ---------------------------------------------------------------------------


def _action(action: str, days_ago: int, firm: str = "test") -> AnalystAction:
    d = (date.fromisoformat(END_DATE) - timedelta(days=days_ago)).isoformat()
    return AnalystAction(
        ticker="AAPL", action_date=d, firm=firm,
        from_grade=None, to_grade=None, action=action,
    )


class _StubAnalystClient:
    """Minimal stand-in implementing only the two analyst methods."""

    def __init__(self, actions: list[AnalystAction], target: AnalystTarget | None):
        self._actions = actions
        self._target = target

    def get_analyst_actions(self, ticker, *, end_date, start_date, limit=100):
        return self._actions

    def get_analyst_targets(self, ticker, *, asof_date=None):
        return self._target


class TestAnalystRatingDetector:
    def test_fires_on_recent_upgrade_cluster(self):
        from v2.scanner.detectors import AnalystRatingDetector
        # Recent 7d: 3 upgrades + 1 init. Baseline 83d: scattered light activity.
        recent = [
            _action("up", days_ago=1, firm="Morgan Stanley"),
            _action("up", days_ago=2, firm="GS"),
            _action("up", days_ago=4, firm="JPM"),
            _action("init", days_ago=5, firm="Citi"),
        ]
        baseline = [
            _action("main", days_ago=20),
            _action("main", days_ago=40),
            _action("down", days_ago=60),
        ]
        fd = _StubAnalystClient(recent + baseline, None)
        trig = AnalystRatingDetector().detect("AAPL", END_DATE, fd)
        assert trig is not None
        assert trig.triggered is True
        assert trig.direction == "bullish"
        assert trig.severity_z > 0
        assert "net actions" in trig.reason

    def test_does_not_fire_on_target_gap_alone(self):
        from v2.scanner.detectors import AnalystRatingDetector
        # Big +25% target gap but zero recent action flow → no trigger.
        # Wall St consensus is structurally bullish; static gap is not event-like.
        target = AnalystTarget(
            ticker="AAPL", current_price=100.0, target_mean=125.0,
            target_median=120.0, target_high=140.0, target_low=110.0,
            n_analysts=15, asof_date=END_DATE,
        )
        fd = _StubAnalystClient([], target)
        trig = AnalystRatingDetector().detect("AAPL", END_DATE, fd)
        assert trig is not None
        assert trig.triggered is False
        # gap is still surfaced in components for inspection.
        assert trig.components["gap"] > 0.2

    def test_does_not_fire_on_negative_target_gap_alone(self):
        from v2.scanner.detectors import AnalystRatingDetector
        # Stock 25% above consensus → bearish gap but no action flow → no trigger.
        target = AnalystTarget(
            ticker="AAPL", current_price=100.0, target_mean=75.0,
            asof_date=END_DATE,
        )
        fd = _StubAnalystClient([], target)
        trig = AnalystRatingDetector().detect("AAPL", END_DATE, fd)
        assert trig.triggered is False
        assert trig.components["gap"] < -0.2

    def test_does_not_fire_on_quiet_baseline(self):
        from v2.scanner.detectors import AnalystRatingDetector
        # 1 upgrade in recent week against a steady drip of 1/week historically.
        # Offset by 1 day so each upgrade lands cleanly in one 7-day bucket.
        actions = [_action("up", days_ago=i * 7 + 1) for i in range(0, 12)]
        target = AnalystTarget(
            ticker="AAPL", current_price=100.0, target_mean=105.0,
            asof_date=END_DATE,
        )
        fd = _StubAnalystClient(actions, target)
        trig = AnalystRatingDetector().detect("AAPL", END_DATE, fd)
        # Recent week looks like every other week; gap is only +5%.
        assert trig is not None
        assert trig.triggered is False

    def test_returns_none_when_client_lacks_analyst_methods(self):
        from v2.scanner.detectors import AnalystRatingDetector
        # MagicMock auto-creates attrs, so use plain object to truly lack methods.
        class _Bare:
            pass
        assert AnalystRatingDetector().detect("AAPL", END_DATE, _Bare()) is None

    def test_handles_exception_in_actions_gracefully(self):
        from v2.scanner.detectors import AnalystRatingDetector

        class _Broken:
            def get_analyst_actions(self, *a, **kw):
                raise RuntimeError("scraper broke")
            def get_analyst_targets(self, *a, **kw):
                return None

        trig = AnalystRatingDetector().detect("AAPL", END_DATE, _Broken())
        # With no usable data on either sub-signal, won't trigger but also
        # won't crash.
        assert trig is not None
        assert trig.triggered is False


# ---------------------------------------------------------------------------
# compute_composite
# ---------------------------------------------------------------------------


class TestComputeComposite:
    def test_no_triggered_returns_none(self):
        triggers = [
            EventTrigger(detector="earnings_surprise", triggered=False),
            EventTrigger(detector="insider_cluster", triggered=False),
        ]
        assert compute_composite("AAPL", triggers, None) is None

    def test_event_only_no_quant(self):
        triggers = [
            EventTrigger(
                detector="earnings_surprise",
                triggered=True,
                severity_z=2.5,
                direction="bullish",
            ),
        ]
        out = compute_composite("AAPL", triggers, None)
        assert out is not None
        assert out.ticker == "AAPL"
        assert out.direction == "bullish"
        assert 0.0 < out.event_score <= 100.0
        # quant unavailable -> composite = event_score
        assert out.quant_score is None
        assert out.composite_score == pytest.approx(out.event_score)

    def test_event_plus_quant_mixes(self):
        triggers = [
            EventTrigger(
                detector="earnings_surprise",
                triggered=True,
                severity_z=2.5,
                direction="bullish",
            ),
        ]
        quant = {
            "momentum": SignalResult(signal_name="momentum", value=0.6),
            "value": SignalResult(signal_name="value", value=-0.2),
        }
        # Explicit non-zero quant_weight so this exercises the actual mixing
        # (the DEFAULT is now quant_weight=0 — see test_quant_off_by_default).
        weights = ScannerWeights(event_weight=0.6, quant_weight=0.4)
        out = compute_composite("AAPL", triggers, quant, weights)
        assert out is not None
        assert out.quant_score is not None
        # Composite is a convex combination of event_score and quant_score
        expected = weights.event_weight * out.event_score + weights.quant_weight * out.quant_score
        assert out.composite_score == pytest.approx(expected)

    def test_quant_off_by_default(self):
        """Default weights are quant-OFF (event 1.0 / quant 0.0) after the Phase-3
        finding that the quant overlay dragged the composite. Even with quant
        signals present, the default composite == event_score; the signals are
        still computed (quant_score not None) but carry zero weight. Reversible
        by passing a ScannerWeights with quant_weight > 0."""
        w = ScannerWeights()
        assert w.event_weight == 1.0 and w.quant_weight == 0.0
        triggers = [EventTrigger(detector="earnings_surprise", triggered=True,
                                 severity_z=2.5, direction="bullish")]
        quant = {"momentum": SignalResult(signal_name="momentum", value=0.9)}
        out = compute_composite("AAPL", triggers, quant, w)
        assert out.quant_score is not None  # still computed, just unweighted
        assert out.composite_score == pytest.approx(out.event_score)

    def test_direction_aggregates_signed_severities(self):
        triggers = [
            EventTrigger(detector="a", triggered=True, severity_z=2.0, direction="bullish"),
            EventTrigger(detector="b", triggered=True, severity_z=-1.0, direction="bearish"),
        ]
        out = compute_composite("AAPL", triggers, None)
        assert out.direction == "bullish"  # +2 + -1 = +1 -> bullish

    def test_severity_clipped_at_cap(self):
        triggers = [
            EventTrigger(detector="x", triggered=True, severity_z=10.0, direction="bullish"),
        ]
        out = compute_composite("AAPL", triggers, None)
        # 10 / 5 = 2.0, clipped to 1.0 -> 100
        assert out.event_score == pytest.approx(100.0)

    def test_severity_mult_amplifies_event_score(self):
        # Raw severity 2.0 with mult 1.5 → effective 3.0 → event_score 60.
        # Without mult (1.0): event_score = 2/5 * 100 = 40.
        triggers = [
            EventTrigger(detector="earnings_event", triggered=True,
                         severity_z=2.0, direction="bullish"),
        ]
        weights = ScannerWeights(detector_severity_mult={"earnings_event": 1.5})
        out = compute_composite("AAPL", triggers, None, weights)
        assert out.event_score == pytest.approx(60.0)

    def test_severity_mult_dampens_event_score(self):
        triggers = [
            EventTrigger(detector="news_sentiment_shift", triggered=True,
                         severity_z=3.0, direction="bullish"),
        ]
        weights = ScannerWeights(detector_severity_mult={"news_sentiment_shift": 0.5})
        # 3 * 0.5 = 1.5 → 1.5/5 * 100 = 30
        out = compute_composite("AAPL", triggers, None, weights)
        assert out.event_score == pytest.approx(30.0)

    def test_severity_mult_missing_key_defaults_to_one(self):
        # Detector not in mult dict → multiplier 1.0 → behaves like before the feature.
        triggers = [
            EventTrigger(detector="intraday_move", triggered=True,
                         severity_z=2.5, direction="bullish"),
        ]
        weights = ScannerWeights(detector_severity_mult={"earnings_surprise": 1.5})
        out = compute_composite("AAPL", triggers, None, weights)
        # 2.5 * 1.0 / 5 * 100 = 50
        assert out.event_score == pytest.approx(50.0)

    def test_event_severity_reports_raw_unweighted_max(self):
        # event_severity is the tiebreaker; should NOT include the mult, so
        # different detector mults don't perturb the tiebreaker ordering.
        triggers = [
            EventTrigger(detector="earnings_event", triggered=True,
                         severity_z=3.0, direction="bullish"),
        ]
        weights = ScannerWeights(detector_severity_mult={"earnings_event": 2.0})
        out = compute_composite("AAPL", triggers, None, weights)
        assert out.event_severity == pytest.approx(3.0)
        # event_score uses weighted (3 * 2 = 6, clipped to 5 → 100)
        assert out.event_score == pytest.approx(100.0)

    def test_weighted_direction_sum_can_flip_sign(self):
        # Raw sum: +2 + -3 = -1 → bearish.
        # With mult bullish=2.0 bearish=0.5: +4 + -1.5 = +2.5 → bullish.
        triggers = [
            EventTrigger(detector="earnings_surprise", triggered=True,
                         severity_z=2.0, direction="bullish"),
            EventTrigger(detector="analyst_rating", triggered=True,
                         severity_z=-3.0, direction="bearish"),
        ]
        # First confirm raw bearish
        out_raw = compute_composite("AAPL", triggers, None)
        assert out_raw.direction == "bearish"
        # Now flip via mults
        weights = ScannerWeights(detector_severity_mult={
            "earnings_surprise": 2.0,
            "analyst_rating": 0.5,
        })
        out = compute_composite("AAPL", triggers, None, weights)
        assert out.direction == "bullish"


# ---------------------------------------------------------------------------
# EstimateRevisionDetector — DELETED 2026-05-20. See detectors/__init__.py
# for the removal note. Data-layer plumbing kept (DataClient.get_estimate_revisions
# + EstimateRevisions model) is still tested in v2/data/test_yfinance_client.py.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# BollingerSqueezeDetector
# ---------------------------------------------------------------------------


def _bb_history(*, days: int = 200, base: float = 100.0,
                normal_sigma: float = 1.5, tight_from: int | None = None,
                tight_sigma: float = 0.15, outlier_at: int | None = None,
                outlier_offset: float = 25.0, seed: int = 42):
    """Build a price series for Bollinger-squeeze tests.

    Per-bar close = base + N(0, sigma) where sigma is ``normal_sigma`` by
    default; bars from index ``tight_from`` (inclusive) onward use
    ``tight_sigma`` (a compressed regime). A single outlier can be placed
    at ``outlier_at`` (close shifted by ``outlier_offset``) — used to make
    yesterday's 20-bar window much wider than today's by dropping the
    outlier out of the window between bar N-1 and bar N.
    """
    import numpy as _np
    from v2.data.models import Price
    end = date.fromisoformat(END_DATE)
    out: list[Price] = []
    d = end - timedelta(days=int(days * 1.6) + 30)
    rng = _np.random.default_rng(seed=seed)
    i = 0
    while len(out) < days and d <= end:
        if d.weekday() < 5:
            sigma = tight_sigma if (
                tight_from is not None and i >= tight_from
            ) else normal_sigma
            close = base + float(rng.normal(0, sigma))
            if outlier_at is not None and i == outlier_at:
                close = base + outlier_offset
            out.append(Price(
                open=close, close=close, high=close + 0.1, low=close - 0.1,
                volume=1_000_000, time=d.isoformat(), adjusted_close=close,
            ))
            i += 1
        d += timedelta(days=1)
    return out


class TestBollingerSqueezeDetector:
    def test_fires_on_first_day_entry_into_squeeze(self):
        """The cleanest first-day entry construction: tight-vol from bar 180
        onward (so today's window is all tight → narrow BW → bottom decile)
        AND a single outlier at bar 179 that lives in YESTERDAY's window
        but NOT today's (dragging yesterday's BW above the 10th-pctl line)."""
        from v2.scanner.detectors import BollingerSqueezeDetector
        history = _bb_history(
            days=200, base=100.0,
            normal_sigma=2.0,
            tight_from=180, tight_sigma=0.05,
            outlier_at=179, outlier_offset=20.0,
        )
        fd = MagicMock()
        fd.get_prices.return_value = history
        trig = BollingerSqueezeDetector().detect("AAPL", END_DATE, fd)
        assert trig is not None
        assert trig.triggered is True, f"unexpected: {trig.reason} components={trig.components}"
        assert trig.direction == "neutral"
        assert trig.severity_z == pytest.approx(2.0)
        assert trig.components["percentile_today"] <= 0.10
        assert trig.components["percentile_yesterday"] > 0.10
        assert "first-day squeeze entry" in trig.reason

    def test_does_not_fire_when_already_in_squeeze(self):
        """Tight regime started long enough ago that yesterday's BW window is
        also fully inside the tight regime — both yesterday and today in the
        bottom decile, no fresh entry. Detector must NOT re-fire."""
        from v2.scanner.detectors import BollingerSqueezeDetector
        # tight_from=175 means bars 175..199 are tight (25 bars). Today's
        # window (180..199) is fully tight. Yesterday's window (179..198)
        # is fully tight too. History bandwidths (73..197) are mostly
        # normal-vol — both today and yesterday land in the bottom decile.
        history = _bb_history(
            days=200, base=100.0,
            normal_sigma=2.0, tight_from=175, tight_sigma=0.05,
        )
        fd = MagicMock()
        fd.get_prices.return_value = history
        trig = BollingerSqueezeDetector().detect("AAPL", END_DATE, fd)
        assert trig is not None
        assert trig.triggered is False
        assert trig.components["percentile_today"] <= 0.10
        assert trig.components["percentile_yesterday"] <= 0.10
        assert "already in squeeze" in trig.reason

    def test_does_not_fire_when_no_squeeze(self):
        """Stable normal-vol regime end-to-end. Today's bandwidth lands
        somewhere in the middle of the 126d distribution, percentile > 0.10."""
        from v2.scanner.detectors import BollingerSqueezeDetector
        history = _bb_history(days=200, base=100.0, normal_sigma=1.5)
        fd = MagicMock()
        fd.get_prices.return_value = history
        trig = BollingerSqueezeDetector().detect("AAPL", END_DATE, fd)
        assert trig is not None
        assert trig.triggered is False
        assert trig.components["percentile_today"] > 0.10

    def test_direction_is_always_neutral(self):
        """Squeeze predicts magnitude, not direction."""
        from v2.scanner.detectors import BollingerSqueezeDetector
        history = _bb_history(
            days=200, base=100.0,
            normal_sigma=2.0,
            tight_from=180, tight_sigma=0.05,
            outlier_at=179, outlier_offset=20.0,
        )
        fd = MagicMock()
        fd.get_prices.return_value = history
        trig = BollingerSqueezeDetector().detect("AAPL", END_DATE, fd)
        assert trig.triggered is True
        assert trig.direction == "neutral"

    def test_returns_none_on_insufficient_history(self):
        """Need percentile_window + bb_window + 2 bars (default 148)."""
        from v2.scanner.detectors import BollingerSqueezeDetector
        fd = MagicMock()
        fd.get_prices.return_value = _bb_history(days=100, normal_sigma=1.5)
        assert BollingerSqueezeDetector().detect("AAPL", END_DATE, fd) is None


# ---------------------------------------------------------------------------
# EarningsUpcomingDetector
# ---------------------------------------------------------------------------


class TestEarningsUpcomingDetector:
    @pytest.mark.parametrize("days_to,expected_sev", [
        (0, 5.0),  # earnings today
        (1, 5.0),  # earnings tomorrow — peak
        (2, 4.0),
        (3, 3.0),
        (4, 2.0),
        (5, 1.0),
    ])
    def test_severity_scales_linearly_by_proximity(self, days_to, expected_sev):
        from v2.scanner.detectors import EarningsUpcomingDetector
        ctx = ScanContext(
            ticker="AAPL", end_date=END_DATE,
            upcoming_earnings_days_to={"AAPL": days_to},
        )
        trig = EarningsUpcomingDetector().detect(
            "AAPL", END_DATE, MagicMock(), ctx=ctx,
        )
        assert trig.triggered is True
        assert trig.direction == "neutral"
        assert trig.severity_z == pytest.approx(expected_sev)
        assert trig.components["days_to_earnings"] == float(days_to)

    def test_does_not_fire_without_upcoming_earnings(self):
        """Calendar loaded but this ticker has no event in window."""
        from v2.scanner.detectors import EarningsUpcomingDetector
        ctx = ScanContext(
            ticker="AAPL", end_date=END_DATE,
            upcoming_earnings_days_to={"MSFT": 2},  # populated but no AAPL
        )
        trig = EarningsUpcomingDetector().detect(
            "AAPL", END_DATE, MagicMock(), ctx=ctx,
        )
        assert trig is not None
        assert trig.triggered is False
        assert trig.components["days_to_earnings"] == -1.0

    def test_returns_none_when_ctx_calendar_missing(self):
        """Detector returns None (excludes ticker from stats) when no
        calendar was loaded — distinguishes from 'loaded and no event'."""
        from v2.scanner.detectors import EarningsUpcomingDetector
        ctx = ScanContext(
            ticker="AAPL", end_date=END_DATE,
            upcoming_earnings_days_to=None,
        )
        assert EarningsUpcomingDetector().detect(
            "AAPL", END_DATE, MagicMock(), ctx=ctx,
        ) is None

    def test_direction_always_neutral_on_fire(self):
        from v2.scanner.detectors import EarningsUpcomingDetector
        ctx = ScanContext(
            ticker="AAPL", end_date=END_DATE,
            upcoming_earnings_days_to={"AAPL": 0},
        )
        trig = EarningsUpcomingDetector().detect(
            "AAPL", END_DATE, MagicMock(), ctx=ctx,
        )
        assert trig.direction == "neutral"

    def test_handles_day_outside_lookahead(self):
        """d=10 (someone passed a stale calendar) → not triggered."""
        from v2.scanner.detectors import EarningsUpcomingDetector
        ctx = ScanContext(
            ticker="AAPL", end_date=END_DATE,
            upcoming_earnings_days_to={"AAPL": 10},
        )
        trig = EarningsUpcomingDetector().detect(
            "AAPL", END_DATE, MagicMock(), ctx=ctx,
        )
        assert trig.triggered is False
        assert "outside" in trig.reason


class _Snapshot:
    """Duck-typed snapshot for TargetPriceChangeDetector tests — mimics the
    SQLAlchemy ORM row's attribute surface without depending on the DB."""

    def __init__(self, *, asof_date: str, target_median: float | None,
                 target_mean: float | None = None):
        self.asof_date = asof_date
        self.target_median = target_median
        self.target_mean = target_mean


class TestTargetPriceChangeDetector:
    def _ctx(self, snapshots: list, ticker: str = "AAPL"):
        return ScanContext(
            ticker=ticker, end_date=END_DATE, target_snapshots=snapshots,
        )

    def test_returns_none_when_no_snapshots(self):
        from v2.scanner.detectors import TargetPriceChangeDetector
        trig = TargetPriceChangeDetector().detect(
            "AAPL", END_DATE, MagicMock(), ctx=self._ctx(None),
        )
        assert trig is None

    def test_returns_none_on_single_snapshot_bootstrap(self):
        """Day 1 of using the detector: only today's snapshot exists. Excluded
        from stats (None), NOT triggered=False."""
        from v2.scanner.detectors import TargetPriceChangeDetector
        snaps = [_Snapshot(asof_date=END_DATE, target_median=150.0)]
        trig = TargetPriceChangeDetector().detect(
            "AAPL", END_DATE, MagicMock(), ctx=self._ctx(snaps),
        )
        assert trig is None

    def test_fires_bullish_on_target_raise(self):
        """target_median raised from 140 to 155 over 7 days → +10.7% → fires."""
        from v2.scanner.detectors import TargetPriceChangeDetector
        snaps = [
            _Snapshot(asof_date="2026-05-06", target_median=140.0),
            _Snapshot(asof_date="2026-05-13", target_median=155.0),
        ]
        trig = TargetPriceChangeDetector().detect(
            "AAPL", END_DATE, MagicMock(), ctx=self._ctx(snaps),
        )
        assert trig.triggered is True
        assert trig.direction == "bullish"
        assert trig.severity_z > 0
        # pct_change ≈ 0.1071; severity = 0.1071/0.02 = 5.36, capped at 5.0
        assert trig.severity_z == pytest.approx(5.0)
        assert "+10.71%" in trig.reason

    def test_fires_bearish_on_target_cut(self):
        from v2.scanner.detectors import TargetPriceChangeDetector
        snaps = [
            _Snapshot(asof_date="2026-05-06", target_median=150.0),
            _Snapshot(asof_date="2026-05-13", target_median=135.0),
        ]
        trig = TargetPriceChangeDetector().detect(
            "AAPL", END_DATE, MagicMock(), ctx=self._ctx(snaps),
        )
        assert trig.triggered is True
        assert trig.direction == "bearish"
        assert trig.severity_z < 0

    def test_does_not_fire_on_small_change(self):
        """3% target raise (below 5% default threshold) → triggered=False."""
        from v2.scanner.detectors import TargetPriceChangeDetector
        snaps = [
            _Snapshot(asof_date="2026-05-06", target_median=150.0),
            _Snapshot(asof_date="2026-05-13", target_median=154.5),
        ]
        trig = TargetPriceChangeDetector().detect(
            "AAPL", END_DATE, MagicMock(), ctx=self._ctx(snaps),
        )
        assert trig is not None
        assert trig.triggered is False
        assert "need ≥5" in trig.reason
        assert trig.components["pct_change"] == pytest.approx(0.03)

    def test_uses_oldest_snapshot_within_lookback(self):
        """When multiple snapshots exist in the window, the OLDEST in-window
        anchors the comparison (so a 7-day window captures the full 7d move,
        not just the most recent day-over-day delta)."""
        from v2.scanner.detectors import TargetPriceChangeDetector
        snaps = [
            _Snapshot(asof_date="2026-05-06", target_median=140.0),  # oldest in 7d
            _Snapshot(asof_date="2026-05-10", target_median=148.0),
            _Snapshot(asof_date="2026-05-12", target_median=152.0),
            _Snapshot(asof_date="2026-05-13", target_median=155.0),  # today
        ]
        trig = TargetPriceChangeDetector().detect(
            "AAPL", END_DATE, MagicMock(), ctx=self._ctx(snaps),
        )
        # Compares 155 (today) vs 140 (oldest in 7d window) → +10.71%
        assert trig.triggered is True
        assert trig.components["baseline_target_median"] == pytest.approx(140.0)
        assert trig.components["pct_change"] == pytest.approx(15.0 / 140.0, rel=0.01)

    def test_skips_snapshots_outside_lookback_window(self):
        """Snapshots older than lookback_days are ignored — only recent
        moves trigger."""
        from v2.scanner.detectors import TargetPriceChangeDetector
        snaps = [
            _Snapshot(asof_date="2026-01-01", target_median=100.0),  # too old
            _Snapshot(asof_date="2026-05-12", target_median=154.0),
            _Snapshot(asof_date="2026-05-13", target_median=155.0),
        ]
        # 7-day default → only 2026-05-12 onwards is in window
        trig = TargetPriceChangeDetector().detect(
            "AAPL", END_DATE, MagicMock(), ctx=self._ctx(snaps),
        )
        # 155 vs 154 = 0.65% → below 5% threshold; does NOT fire
        assert trig.triggered is False
        # baseline used the 2026-05-12 row, not the Jan one
        assert trig.components["baseline_target_median"] == pytest.approx(154.0)

    def test_returns_none_when_today_target_missing(self):
        """today_target_median = None (e.g. yfinance scraped a stale row) →
        excluded from stats."""
        from v2.scanner.detectors import TargetPriceChangeDetector
        snaps = [
            _Snapshot(asof_date="2026-05-06", target_median=140.0),
            _Snapshot(asof_date="2026-05-13", target_median=None),
        ]
        trig = TargetPriceChangeDetector().detect(
            "AAPL", END_DATE, MagicMock(), ctx=self._ctx(snaps),
        )
        assert trig is None

    def test_severity_capped(self):
        """Extreme target move (e.g. 50%+) is capped at severity_cap=5.0."""
        from v2.scanner.detectors import TargetPriceChangeDetector
        snaps = [
            _Snapshot(asof_date="2026-05-06", target_median=100.0),
            _Snapshot(asof_date="2026-05-13", target_median=200.0),  # +100%
        ]
        trig = TargetPriceChangeDetector().detect(
            "AAPL", END_DATE, MagicMock(), ctx=self._ctx(snaps),
        )
        assert trig.triggered is True
        assert trig.severity_z == pytest.approx(5.0)  # capped


class TestScannerWeightsValidation:
    def test_default_construction_passes(self):
        w = ScannerWeights()
        assert w.enabled_detectors is None
        assert w.detector_severity_mult == {}

    def test_enabled_detectors_empty_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            ScannerWeights(enabled_detectors=[])

    def test_enabled_detectors_unknown_name_rejected(self):
        with pytest.raises(ValueError, match="unknown detector"):
            ScannerWeights(enabled_detectors=["earnings_event", "no_such_detector"])

    def test_enabled_detectors_valid_passes(self):
        w = ScannerWeights(enabled_detectors=["earnings_event", "intraday_move"])
        assert w.enabled_detectors == ["earnings_event", "intraday_move"]

    def test_enabled_detectors_dedupes_preserving_order(self):
        w = ScannerWeights(enabled_detectors=[
            "earnings_event", "intraday_move", "earnings_event",
        ])
        assert w.enabled_detectors == ["earnings_event", "intraday_move"]

    def test_enabled_detectors_legacy_alias_rewritten(self):
        # Old config rows keyed by the pre-merge detector names ("earnings_surprise",
        # "earnings_upcoming") must still validate AND be rewritten to the
        # canonical "earnings_event" so the rest of the pipeline only sees
        # current names.
        w = ScannerWeights(enabled_detectors=[
            "earnings_surprise", "earnings_upcoming", "intraday_move",
        ])
        assert w.enabled_detectors == ["earnings_event", "intraday_move"]

    def test_severity_mult_unknown_name_rejected(self):
        with pytest.raises(ValueError, match="unknown detector"):
            ScannerWeights(detector_severity_mult={"no_such_detector": 1.0})

    def test_severity_mult_negative_rejected(self):
        with pytest.raises(ValueError, match="out of range"):
            ScannerWeights(detector_severity_mult={"earnings_event": -0.1})

    def test_severity_mult_above_cap_rejected(self):
        with pytest.raises(ValueError, match="out of range"):
            ScannerWeights(detector_severity_mult={"earnings_event": 5.5})

    def test_severity_mult_at_boundary_passes(self):
        w = ScannerWeights(detector_severity_mult={
            "earnings_event": 0.0, "intraday_move": 5.0,
        })
        assert w.detector_severity_mult["earnings_event"] == 0.0
        assert w.detector_severity_mult["intraday_move"] == 5.0

    def test_severity_mult_partial_dict_passes(self):
        # Only one detector specified — others default to 1.0 at scoring time.
        w = ScannerWeights(detector_severity_mult={"earnings_event": 1.5})
        assert "intraday_move" not in w.detector_severity_mult

    def test_severity_mult_legacy_alias_rewritten(self):
        # Pre-merge configs may map "earnings_surprise" -> 1.5 separately from
        # "earnings_upcoming" -> 0.8; after alias rewrite the unified
        # "earnings_event" entry wins, with the first-seen value preserved.
        w = ScannerWeights(detector_severity_mult={
            "earnings_surprise": 1.5, "earnings_upcoming": 0.8,
        })
        assert w.detector_severity_mult == {"earnings_event": 1.5}
