"""Event detectors for the scanner.

Each detector implements ``EventDetector`` and produces an ``EventTrigger``
(triggered or not). The runner aggregates triggered events per ticker and
hands them to ``v2.scanner.scoring.compute_composite``.
"""

from v2.scanner.detectors.analyst_rating import AnalystRatingDetector
from v2.scanner.detectors.base import EventDetector, EventTrigger
from v2.scanner.detectors.bollinger_squeeze import BollingerSqueezeDetector
from v2.scanner.detectors.earnings import (
    EarningsEventDetector,
    EarningsSurpriseDetector,
)
from v2.scanner.detectors.earnings_upcoming import EarningsUpcomingDetector
from v2.scanner.detectors.gap import GapDetector
from v2.scanner.detectors.high_breakout import HighBreakoutDetector
from v2.scanner.detectors.insider import InsiderClusterDetector
from v2.scanner.detectors.ma_cross import MaCrossDetector
from v2.scanner.detectors.intraday_move import IntradayMoveDetector
from v2.scanner.detectors.news_sentiment import NewsSentimentShiftDetector
from v2.scanner.detectors.obv_divergence import OBVDivergenceDetector
from v2.scanner.detectors.rsi_divergence import RsiDivergenceDetector
from v2.scanner.detectors.target_price_change import TargetPriceChangeDetector
from v2.scanner.detectors.volume_anomaly import VolumeAnomalyDetector

ALL_DETECTORS: tuple[type[EventDetector], ...] = (
    EarningsEventDetector,
    InsiderClusterDetector,
    IntradayMoveDetector,
    AnalystRatingDetector,
    TargetPriceChangeDetector,
    BollingerSqueezeDetector,
    RsiDivergenceDetector,
    MaCrossDetector,
    # UNREGISTERED 2026-06-01 as net-counterproductive / broken pre-filters per the
    # regime-segmented eval (findings_scanner_eval.md + findings_scanner_round2.md).
    # Flagged events had significantly NEGATIVE interestingness-vs-random — they flag
    # stocks that then move LESS than a random pick, worst in the bear regime:
    #   * HighBreakoutDetector   (high_breakout,        t=-4.2 / -4.4)
    #   * OBVDivergenceDetector  (obv_divergence,       t=-4.3 / -2.4)
    #   * NewsSentimentShiftDetector (news_sentiment_shift, t=-5.0 — also the
    #       long-planned removal as sentiment moves to the LLM agent layer)
    #   * VolumeAnomalyDetector  (price_volume_anomaly, flat-day volume ≈0/neg)
    #   * GapDetector (gap) — RETIRED 2026-06-01 (round-2): z-scoring is BROKEN (a
    #       5σ threshold still fires on ~49% of bear ticker-days), interestingness
    #       negative at every swept threshold 3.0–5.0σ. No sane threshold exists.
    #       See findings_scanner_round2.md.
    # Classes remain importable + re-registerable (files retained); drop them
    # back into this tuple + DETECTOR_METADATA to re-enable.
    #
    # EarningsSurpriseDetector + EarningsUpcomingDetector — UNREGISTERED
    # 2026-05-18. Merged into the unified ``EarningsEventDetector`` above.
    # The two old classes remain importable for back-compat with tests and
    # any persisted ScannerConfig keyed by the old detector names; the
    # legacy keys are aliased to ``earnings_event`` in DETECTOR_METADATA
    # below so old config rows still produce a working detector list.
    #
    # EstimateRevisionDetector — DELETED 2026-05-20. Was UNREGISTERED on
    # 2026-05-15 because yfinance's ``eps_revisions`` field had incoherent
    # semantics (observed up_7d > up_30d for AAPL/MSFT/TSLA which is
    # impossible if cumulative). The intended signal is now served by
    # TargetPriceChangeDetector (M9.d, DB-backed snapshots). Data-layer
    # plumbing (DataClient.get_estimate_revisions + EstimateRevisions
    # model) intentionally KEPT — general-purpose, callable if a future
    # detector wants to re-attempt with a different data source.
)


# UI metadata + recommended ("academic prior") severity multipliers per
# detector. Source for the GET /scanner/detectors endpoint and for the
# "Recommended defaults" preset button in the config dialog. Default values
# follow task_plan_scanner_v2.md §4.2: PEAD strongest, ANLY structurally
# lagging, news removed (kept here at 0.50 as transitional under-weight
# until the formal removal in §5).
DETECTOR_METADATA: dict[str, dict] = {
    "earnings_event": {
        "label": "Earnings Event",
        "default_mult": 1.20,
        "description": (
            "Unified earnings catalyst window: fires 5 business days BEFORE a "
            "scheduled report (severity ramps 1→5 by proximity, direction "
            "neutral) OR up to 5 business days AFTER a filing (severity z-scored "
            "vs trailing 4 quarters' surprises, direction bullish on BEAT / "
            "bearish on MISS). Components include signed biz_days_to_event "
            "(negative = future, positive = past) and a phase flag."
        ),
    },
    "insider_cluster": {
        "label": "Insider Cluster",
        "default_mult": 1.00,
        "description": "Coordinated insider buys/sells inside the last 30 days vs trailing baseline.",
    },
    "intraday_move": {
        "label": "Intraday Move",
        "default_mult": 1.10,
        "description": "Outsized intraday return / overnight gap / range, SPY/QQQ-relative.",
    },
    "analyst_rating": {
        "label": "Analyst Rating",
        "default_mult": 0.90,
        "description": "Net upgrade/downgrade flow z-scored vs trailing 90-day baseline.",
    },
    "target_price_change": {
        "label": "Target Price Shift",
        "default_mult": 1.00,
        "description": "Median analyst price target moved by ≥5% over 7 days. DB-snapshot backed.",
    },
    "bollinger_squeeze": {
        "label": "Bollinger Squeeze",
        "default_mult": 0.80,
        "description": "First-day entry into 20d Bollinger bandwidth ≤10th percentile of 126d — statistical setup for imminent directional move. Direction neutral.",
    },
    "rsi_divergence": {
        "label": "RSI Divergence",
        "default_mult": 1.00,
        "description": (
            "Classic price-vs-RSI(14) divergence over a 40-bar window split into "
            "two 20-bar halves. Bearish: recent price high > older price high BUT "
            "RSI at that high is lower. Bullish: recent price low < older price low "
            "BUT RSI at that low is higher. Severity = RSI gap / 10, capped at 8."
        ),
    },
    "ma_cross": {
        "label": "Golden/Death Cross",
        "default_mult": 1.00,
        "description": (
            "Fires on the day SMA(50) crosses SMA(200). Golden cross (SMA50 crosses "
            "above SMA200) → bullish; death cross (SMA50 crosses below SMA200) → bearish. "
            "Requires ≥202 bars. Severity is fixed at 2.0 — a cross is a binary regime "
            "event, not a z-scored quantity; no std divisor is used."
        ),
    },
}


# Legacy keys → unified detector. Persisted ScannerConfig rows from before
# 2026-05-18 may still reference "earnings_surprise" / "earnings_upcoming"
# in their detector_severity_mult / enabled_detectors maps; the runner
# resolves these via this alias map so old configs keep working without a
# DB migration. New configs should use "earnings_event" directly.
LEGACY_DETECTOR_ALIASES: dict[str, str] = {
    "earnings_surprise": "earnings_event",
    "earnings_upcoming": "earnings_event",
}


# Detectors that were registered once but have been retired (unregistered from
# ALL_DETECTORS). Persisted ScannerConfig rows may still list these in their
# enabled_detectors / detector_severity_mult; the ScannerWeights validators
# accept them (so old configs still load) but the runner no longer has a
# matching detector, so they're harmless no-ops. Re-register a name (move its
# class back into ALL_DETECTORS + DETECTOR_METADATA) to revive it.
RETIRED_DETECTORS: frozenset[str] = frozenset(
    {
        "high_breakout",
        "obv_divergence",
        "news_sentiment_shift",
        "price_volume_anomaly",
        "gap",
    }
)


__all__ = [
    "EventDetector",
    "EventTrigger",
    "EarningsEventDetector",
    "EarningsSurpriseDetector",
    "InsiderClusterDetector",
    "VolumeAnomalyDetector",
    "NewsSentimentShiftDetector",
    "IntradayMoveDetector",
    "AnalystRatingDetector",
    "TargetPriceChangeDetector",
    "BollingerSqueezeDetector",
    "EarningsUpcomingDetector",
    "OBVDivergenceDetector",
    "RsiDivergenceDetector",
    "HighBreakoutDetector",
    "GapDetector",
    "MaCrossDetector",
    "ALL_DETECTORS",
    "DETECTOR_METADATA",
    "LEGACY_DETECTOR_ALIASES",
    "RETIRED_DETECTORS",
]
