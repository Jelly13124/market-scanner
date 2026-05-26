"""Composite scoring: combine event severity with quant factor signals.

Inputs:
    * List of EventTriggers (only triggered ones contribute)
    * Optional dict of factor-name -> SignalResult (v2.models.SignalResult)
    * ScannerWeights (event vs quant weights + per-factor weights)

Output:
    * ScoredEntry (or None if no event triggered — the ticker isn't a candidate)

Score components, all on 0-100 scale:
    event_score   = clip(max(|severity_z|) / 5, 0, 1) * 100
    quant_score   = weighted mean of ((signal.value + 1) / 2 * 100) for factors
                    whose weight is non-zero in ScannerWeights.factor_weights
                    AND that exist in the supplied quant dict (renormalized).
    composite     = event_weight * event_score + quant_weight * quant_score
                    (when quant_score is None, composite = event_score)

Direction is the sign of the weighted sum of triggered severity_z's, mapping to
'bullish' / 'bearish' / 'neutral'.
"""

from __future__ import annotations

from typing import Mapping

from v2.models import SignalResult
from v2.scanner.detectors.base import EventTrigger
from v2.scanner.models import Direction, ScannerWeights, ScoredEntry

# Cap the severity z used in event_score normalization. 5σ moves are extreme
# enough that scoring beyond them adds noise, not information.
_SEVERITY_CLIP = 5.0


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _direction_from(
    triggered: list[EventTrigger],
    severity_mult: dict[str, float] | None = None,
) -> Direction:
    """Direction is the sign of the (optionally weighted) sum of triggered
    severities. ``severity_mult`` missing keys default to 1.0 — a detector
    not present in the dict contributes its raw severity_z."""
    mults = severity_mult or {}
    s = sum(t.severity_z * mults.get(t.detector, 1.0) for t in triggered)
    if s > 1e-6:
        return "bullish"
    if s < -1e-6:
        return "bearish"
    return "neutral"


def _quant_subscore(
    quant: Mapping[str, SignalResult] | None,
    factor_weights: dict[str, float],
) -> float | None:
    """Return a 0-100 score, or None if no factor has both a weight and a signal."""
    if not quant:
        return None
    present = {
        name: w for name, w in factor_weights.items() if w > 0 and name in quant
    }
    if not present:
        return None
    total_w = sum(present.values())
    if total_w <= 0:
        return None
    score = 0.0
    for name, w in present.items():
        val = float(quant[name].value)
        # Map [-1, +1] -> [0, 100]
        scaled = (max(-1.0, min(1.0, val)) + 1.0) / 2.0 * 100.0
        score += (w / total_w) * scaled
    return score


def compute_composite(
    ticker: str,
    triggers: list[EventTrigger],
    quant: Mapping[str, SignalResult] | None,
    weights: ScannerWeights | None = None,
) -> ScoredEntry | None:
    """Build a ScoredEntry from detector outputs.

    Returns ``None`` if no triggers fired — the ticker is not a watchlist
    candidate.
    """
    weights = weights or ScannerWeights()
    triggered = [t for t in triggers if t.triggered]
    if not triggered:
        return None

    # Apply per-detector severity multiplier BEFORE max-takes-all so a
    # high-quality detector (e.g. earnings_surprise at mult=1.20) outranks
    # a noisier one (e.g. news at 0.50) at equal raw severity. Missing
    # entries default to 1.0 — neutral. ``event_severity`` reports the
    # un-multiplied raw max for the deterministic tiebreaker (see
    # ScoredEntry.event_severity docstring).
    mults = weights.detector_severity_mult or {}
    raw_severity = max((abs(t.severity_z) for t in triggered), default=0.0)
    weighted_severity = max(
        (abs(t.severity_z) * mults.get(t.detector, 1.0) for t in triggered),
        default=0.0,
    )
    event_score = _clip(weighted_severity / _SEVERITY_CLIP, 0.0, 1.0) * 100.0

    quant_score = _quant_subscore(quant, weights.factor_weights)

    if quant_score is None:
        composite = event_score
    else:
        composite = weights.event_weight * event_score + weights.quant_weight * quant_score

    composite = _clip(composite, 0.0, 100.0)
    direction = _direction_from(triggered, mults)

    return ScoredEntry(
        ticker=ticker,
        composite_score=composite,
        direction=direction,
        event_score=event_score,
        quant_score=quant_score,
        event_severity=raw_severity,
        triggers=[t.model_dump() for t in triggered],
        rank=0,
    )
