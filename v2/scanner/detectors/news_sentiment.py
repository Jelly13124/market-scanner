"""News sentiment shift detector.

Uses FD's per-article ``sentiment`` label (positive / negative / neutral).
Articles within the trailing ``recent_window_days`` are averaged into a
short-term polarity; the trailing ``baseline_window_days`` (excluding the
recent window) form the baseline distribution. The z-score of the short-term
mean against the baseline is the severity.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np

from v2.data.protocol import DataClient
from v2.scanner.detectors.base import EventDetector, EventTrigger, parse_date as _parse_date
from v2.scanner.models import ScanContext

_POLARITY = {
    "positive": 1.0,
    "negative": -1.0,
    "neutral": 0.0,
}




def _polarity(label: str | None) -> float | None:
    if not label:
        return None
    return _POLARITY.get(label.strip().lower())


class NewsSentimentShiftDetector(EventDetector):
    """Trigger when recent-window news sentiment diverges from the baseline."""

    name = "news_sentiment_shift"

    def __init__(
        self,
        *,
        recent_window_days: int = 7,
        baseline_window_days: int = 90,
        min_recent_articles: int = 3,
        min_baseline_articles: int = 10,
        z_threshold: float = 2.0,
        fetch_limit: int = 500,
    ) -> None:
        self._recent_window = recent_window_days
        self._baseline_window = baseline_window_days
        self._min_recent = min_recent_articles
        self._min_baseline = min_baseline_articles
        self._z_thresh = z_threshold
        self._fetch_limit = fetch_limit

    def detect(
        self,
        ticker: str,
        end_date: str,
        fd: DataClient,
        *,
        ctx: ScanContext | None = None,
    ) -> EventTrigger | None:
        today = _parse_date(end_date)
        if today is None:
            return None

        start = (today - timedelta(days=self._baseline_window)).isoformat()
        articles = fd.get_news(
            ticker, end_date=end_date, start_date=start, limit=self._fetch_limit,
        )
        if not articles:
            return None

        recent_cutoff = today - timedelta(days=self._recent_window)
        recent_pol: list[float] = []
        baseline_pol: list[float] = []
        for art in articles:
            d = _parse_date(art.date) if art.date else None
            # Prefer the continuous score when the provider supplies one
            # (EODHD's daily aggregate). Falls back to the 3-bucket label,
            # which is what FD returns and what mocked tests use.
            if art.sentiment_score is not None:
                pol = float(art.sentiment_score)
            else:
                pol = _polarity(art.sentiment)
            if d is None or pol is None:
                continue
            if d >= recent_cutoff:
                recent_pol.append(pol)
            else:
                baseline_pol.append(pol)

        if len(recent_pol) < self._min_recent:
            return EventTrigger(
                detector=self.name,
                triggered=False,
                reason=f"only {len(recent_pol)} scored articles in last {self._recent_window}d",
                components={
                    "recent_count": float(len(recent_pol)),
                    "baseline_count": float(len(baseline_pol)),
                },
                asof_date=end_date,
            )

        if len(baseline_pol) < self._min_baseline:
            return EventTrigger(
                detector=self.name,
                triggered=False,
                reason=f"only {len(baseline_pol)} baseline articles",
                components={
                    "recent_count": float(len(recent_pol)),
                    "baseline_count": float(len(baseline_pol)),
                },
                asof_date=end_date,
            )

        recent_arr = np.array(recent_pol)
        baseline_arr = np.array(baseline_pol)
        recent_mean = float(recent_arr.mean())
        baseline_mean = float(baseline_arr.mean())
        # Minimum baseline std of 0.10 — polarity ranges [-1, +1], and a real
        # sentiment baseline almost always has at least ±0.1 spread. Without
        # this floor, a perfectly homogeneous baseline (std=0) collapsed to
        # 1e-6 and produced wildly unreliable z-scores like ±300,000.
        baseline_std = max(float(baseline_arr.std(ddof=1)), 0.10)
        z = (recent_mean - baseline_mean) / baseline_std

        components = {
            "recent_count": float(len(recent_pol)),
            "baseline_count": float(len(baseline_pol)),
            "recent_mean": float(recent_mean),
            "baseline_mean": float(baseline_mean),
            "baseline_std": float(baseline_std),
            "raw_z": float(z),
        }

        if abs(z) < self._z_thresh:
            return EventTrigger(
                detector=self.name,
                triggered=False,
                reason=f"shift z={z:+.2f} below threshold",
                components=components,
                asof_date=end_date,
            )

        if recent_mean > baseline_mean:
            direction = "bullish"
        elif recent_mean < baseline_mean:
            direction = "bearish"
        else:
            direction = "neutral"

        return EventTrigger(
            detector=self.name,
            triggered=True,
            severity_z=float(z),
            direction=direction,
            reason=(
                f"recent polarity {recent_mean:+.2f} vs baseline {baseline_mean:+.2f} "
                f"(z={z:+.2f}, n_recent={len(recent_pol)})"
            ),
            components=components,
            asof_date=end_date,
        )
