"""Phase 6A: 3 entry-filter block Pydantic models. ALL filters must pass."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TrendFilter(BaseModel):
    type: Literal["trend"] = "trend"
    ma_period: int = Field(default=200, ge=2, le=500)
    ma_type: Literal["sma", "ema"] = "sma"
    direction: Literal["rising", "falling"]


class VolatilityFilter(BaseModel):
    type: Literal["volatility"] = "volatility"
    atr_period: int = Field(default=14, ge=2, le=100)
    percentile_min: float = Field(default=0, ge=0, le=100)
    percentile_max: float = Field(default=100, ge=0, le=100)


class LiquidityFilter(BaseModel):
    type: Literal["liquidity"] = "liquidity"
    min_daily_dollar_volume: float = Field(default=1_000_000, ge=0)
    lookback_days: int = Field(default=20, ge=2, le=252)
