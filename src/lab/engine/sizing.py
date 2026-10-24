"""Phase 6B: compute dollar value for a new position given current state."""

from __future__ import annotations

from src.lab.spec.blocks_sizing import (
    EqualWeightSizing, FixedPctSizing, VolTargetedSizing,
)


def compute_position_dollars(
    sizing,
    *,
    cash: float,
    total_equity: float,
    current_positions: int,
    current_atr: float,
) -> float:
    """Return target dollar value for a new position.

    Caller divides by current price → integer share count.

    Behaviour:
      - FixedPctSizing: pct × total_equity
      - EqualWeightSizing: cash / (current_positions + 1)
      - VolTargetedSizing: target_dollar_vol_per_position × 10
        (heuristic — sizes inversely to ATR via downstream share calc)
    """
    if cash <= 0:
        return 0.0

    if isinstance(sizing, FixedPctSizing):
        return float(total_equity) * sizing.pct

    if isinstance(sizing, EqualWeightSizing):
        denom = current_positions + 1
        return float(cash) / denom

    if isinstance(sizing, VolTargetedSizing):
        # We aim for a fixed dollar vol per position. Without price here
        # we return a scaled dollar amount; caller computes shares =
        # target / price, and the ATR scaling happens via stop sizing
        # downstream. Simple v1 heuristic.
        if current_atr <= 0:
            return 0.0
        # Notional ~ target_dollar_vol × multiplier; cap at 10% equity
        notional = sizing.target_dollar_vol_per_position * 10
        return min(notional, total_equity * 0.10)

    raise ValueError(f"Unknown sizing block type: {sizing.type}")
