"""Analyst rating detector.

Triggers on the **net upgrade score** — weighted sum of the last 7 days'
analyst actions (up=+1, init=+0.5, main=0, down=-1, reit=0), z-scored
against the distribution of 7-day windows over the trailing 90 days.

Target gap (target_mean vs current_price) is captured in ``components``
for inspection but is **not** a gating signal — Wall Street consensus
is structurally bullish, so static target offsets fire on most names
and aren't event-like.

Requires a ``DataClient`` that implements ``get_analyst_actions`` and
``get_analyst_targets`` (``AnalystDataClient`` sub-protocol — yfinance via
``CompositeClient``). If those methods are absent or all calls return empty,
the detector returns ``None`` cleanly — same convention as the rest of the
pipeline.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

import numpy as np

from v2.data.protocol import DataClient
from v2.scanner.detectors.base import EventDetector, EventTrigger, parse_date as _parse_date
from v2.scanner.models import ScanContext

logger = logging.getLogger(__name__)


# Per-action weights for the net-upgrade score.
_ACTION_WEIGHT = {
    "up": 1.0,
    "init": 0.5,
    "main": 0.0,
    "reit": 0.0,
    "down": -1.0,
}




def _score_actions(actions: list, start: date, end: date) -> float:
    """Sum of action weights for events with action_date in [start, end]."""
    total = 0.0
    for a in actions:
        d = _parse_date(a.action_date)
        if d is None or d < start or d > end:
            continue
        total += _ACTION_WEIGHT.get(a.action, 0.0)
    return total


class AnalystRatingDetector(EventDetector):
    """Trigger on a fresh wave of upgrades/downgrades."""

    name = "analyst_rating"

    def __init__(
        self,
        *,
        recent_window_days: int = 7,
        baseline_window_days: int = 90,
        net_z_threshold: float = 2.0,
        gap_z_scale: float = 0.05,
        score_std_floor: float = 0.5,
        action_fetch_limit: int = 200,
    ) -> None:
        self._recent = recent_window_days
        self._baseline = baseline_window_days
        self._net_thresh = net_z_threshold
        # gap_z_scale only used to compute the inspection-only gap_z in
        # ``components``; not part of the gating logic.
        self._gap_scale = gap_z_scale
        self._score_floor = score_std_floor
        self._fetch_limit = action_fetch_limit

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

        # If the configured client doesn't expose analyst data, exit cleanly.
        if not (hasattr(fd, "get_analyst_actions") and hasattr(fd, "get_analyst_targets")):
            return None

        baseline_start = today - timedelta(days=self._baseline)
        try:
            actions = fd.get_analyst_actions(
                ticker,
                end_date=end_date,
                start_date=baseline_start.isoformat(),
                limit=self._fetch_limit,
            )
        except (NotImplementedError, AttributeError):
            return None
        except Exception as e:
            logger.warning("analyst_rating: get_analyst_actions(%s) failed: %s", ticker, e)
            actions = []

        try:
            target = fd.get_analyst_targets(ticker, asof_date=end_date)
        except (NotImplementedError, AttributeError):
            target = None
        except Exception as e:
            logger.warning("analyst_rating: get_analyst_targets(%s) failed: %s", ticker, e)
            target = None

        # ------------------------------------------------------------------
        # Sub-signal 1: net upgrade score z-scored vs baseline 7d windows
        # ------------------------------------------------------------------
        recent_cutoff = today - timedelta(days=self._recent)
        recent_score = _score_actions(actions or [], recent_cutoff, today)

        # Build non-overlapping 7-day baseline buckets between
        # [today - baseline, today - recent]. Roughly (90-7)/7 ≈ 12 samples.
        baseline_scores: list[float] = []
        bucket_end = recent_cutoff
        bucket_window = timedelta(days=self._recent)
        while bucket_end - bucket_window >= baseline_start:
            bucket_start = bucket_end - bucket_window + timedelta(days=1)
            baseline_scores.append(
                _score_actions(actions or [], bucket_start, bucket_end)
            )
            bucket_end = bucket_start - timedelta(days=1)

        net_z = 0.0
        baseline_mean = 0.0
        baseline_std = 0.0
        if len(baseline_scores) >= 2:
            arr = np.array(baseline_scores)
            baseline_mean = float(arr.mean())
            # Score std floor: 0.5 weight-points. Without it, a stretch of
            # zero-action weeks collapses std to 0 and z explodes.
            baseline_std = max(float(arr.std(ddof=1)), self._score_floor)
            net_z = (recent_score - baseline_mean) / baseline_std

        # ------------------------------------------------------------------
        # Sub-signal 2: target_mean / current_price gap
        # ------------------------------------------------------------------
        gap = 0.0
        gap_z = 0.0
        target_mean = None
        current_price = None
        if target is not None:
            target_mean = target.target_mean
            current_price = target.current_price
            if (target_mean is not None and current_price is not None
                    and current_price > 0):
                gap = (target_mean - current_price) / current_price
                gap_z = gap / self._gap_scale  # 5% per "unit" of consensus disagreement

        # ------------------------------------------------------------------
        # Gating — net upgrade flow only. Target gap is inspection-only.
        # ------------------------------------------------------------------
        net_hit = abs(net_z) >= self._net_thresh

        components = {
            "recent_score": float(recent_score),
            "baseline_mean": float(baseline_mean),
            "baseline_std": float(baseline_std),
            "baseline_n": float(len(baseline_scores)),
            "net_z": float(net_z),
            "target_mean": float(target_mean) if target_mean is not None else 0.0,
            "current_price": float(current_price) if current_price is not None else 0.0,
            "gap": float(gap),
            "gap_z": float(gap_z),
            "actions_in_window": float(len([
                a for a in (actions or [])
                if (_parse_date(a.action_date) or today) >= recent_cutoff
            ])),
        }

        if not net_hit:
            return EventTrigger(
                detector=self.name,
                triggered=False,
                reason=f"net z={net_z:+.2f} (score={recent_score:+.1f})",
                components=components,
                asof_date=end_date,
            )

        severity = net_z
        direction = "bullish" if net_z > 0 else "bearish"
        reason = f"net actions z={net_z:+.2f} (score={recent_score:+.1f})"

        return EventTrigger(
            detector=self.name,
            triggered=True,
            severity_z=float(severity),
            direction=direction,
            reason=reason,
            components=components,
            asof_date=end_date,
        )
