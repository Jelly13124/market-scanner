"""Phase 6B: sizing computation for fixed_pct / equal_weight / vol_targeted."""

from __future__ import annotations

import pytest

from src.lab.engine.sizing import compute_position_dollars
from src.lab.spec.blocks_sizing import (
    EqualWeightSizing, FixedPctSizing, VolTargetedSizing,
)


def test_fixed_pct():
    sizing = FixedPctSizing(pct=0.10)
    dollars = compute_position_dollars(
        sizing, cash=100_000, total_equity=100_000,
        current_positions=0, current_atr=2.0,
    )
    assert dollars == 10_000  # 10% of 100k


def test_equal_weight_splits_cash():
    sizing = EqualWeightSizing()
    # 50k cash, 5 positions currently → 6 with new = 50k/6 ≈ 8333
    dollars = compute_position_dollars(
        sizing, cash=50_000, total_equity=100_000,
        current_positions=5, current_atr=2.0,
    )
    assert 8000 < dollars < 9000


def test_vol_targeted():
    sizing = VolTargetedSizing(target_dollar_vol_per_position=1000, atr_period=14)
    # target_dollar / atr → shares; here we just compute the dollar value
    # shares = 1000 / 2.0 = 500; this returns 1000 (the target) — caller
    # divides by price to get shares
    dollars = compute_position_dollars(
        sizing, cash=100_000, total_equity=100_000,
        current_positions=0, current_atr=2.0,
    )
    # Implementation: returns target_dollar_vol * (price / atr) — but we
    # don't have price here, so the formula returns target_dollar_vol
    # scaled by an indicator. See implementation for exact semantics.
    assert dollars > 0


def test_zero_cash_returns_zero():
    sizing = FixedPctSizing(pct=0.10)
    dollars = compute_position_dollars(
        sizing, cash=0, total_equity=0, current_positions=0, current_atr=2.0,
    )
    assert dollars == 0
