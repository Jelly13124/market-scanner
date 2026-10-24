"""Phase 6A: 3 position-sizing block Pydantic models. Spec picks ONE."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FixedPctSizing(BaseModel):
    type: Literal["fixed_pct"] = "fixed_pct"
    pct: float = Field(default=0.05, ge=0.005, le=1.0)


class EqualWeightSizing(BaseModel):
    type: Literal["equal_weight"] = "equal_weight"
    # Splits available cash across current + new positions at entry time.
    # V1 does not rebalance — once allocated, position stays at allocated $.


class VolTargetedSizing(BaseModel):
    type: Literal["vol_targeted"] = "vol_targeted"
    target_dollar_vol_per_position: float = Field(default=1000, gt=0)
    atr_period: int = Field(default=14, ge=2, le=100)
