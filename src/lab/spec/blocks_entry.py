"""Phase 6A: 8 entry signal block Pydantic models.

Each block has:
  - ``type``: Literal discriminator (matches block name)
  - tunable parameters with Field(ge=, le=) range bounds

LLM picks these via with_structured_output(StrategySpec, method="json_mode");
Pydantic rejects out-of-range parameters at construction.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RSIEntry(BaseModel):
    type: Literal["rsi"] = "rsi"
    period: int = Field(default=14, ge=2, le=100)
    level: float = Field(default=30, ge=0, le=100)
    direction: Literal["oversold_buy", "overbought_short"]


class RSICrossEntry(BaseModel):
    type: Literal["rsi_cross"] = "rsi_cross"
    period: int = Field(default=14, ge=2, le=100)
    level: float = Field(default=30, ge=0, le=100)
    direction: Literal["up", "down"]


class MACrossEntry(BaseModel):
    type: Literal["ma_cross"] = "ma_cross"
    fast: int = Field(default=50, ge=2, le=500)
    slow: int = Field(default=200, ge=2, le=500)
    ma_type: Literal["sma", "ema"] = "sma"
    direction: Literal["golden", "death"] = "golden"


class PriceVsMAEntry(BaseModel):
    type: Literal["price_vs_ma"] = "price_vs_ma"
    ma_period: int = Field(default=200, ge=2, le=500)
    ma_type: Literal["sma", "ema"] = "sma"
    direction: Literal["above", "below"]


class MACDEntry(BaseModel):
    type: Literal["macd"] = "macd"
    fast: int = Field(default=12, ge=2, le=100)
    slow: int = Field(default=26, ge=2, le=200)
    signal: int = Field(default=9, ge=2, le=100)
    trigger: Literal[
        "bullish_cross", "bearish_cross",
        "histogram_flip_up", "histogram_flip_down",
    ]


class BollingerBreakEntry(BaseModel):
    type: Literal["bollinger_break"] = "bollinger_break"
    period: int = Field(default=20, ge=2, le=200)
    num_std: float = Field(default=2.0, ge=0.5, le=5.0)
    direction: Literal["break_up", "break_down"]


class DonchianBreakEntry(BaseModel):
    type: Literal["donchian_break"] = "donchian_break"
    period: int = Field(default=20, ge=2, le=252)
    direction: Literal["break_up", "break_down"]


class VolumeSpikeEntry(BaseModel):
    type: Literal["volume_spike"] = "volume_spike"
    avg_period: int = Field(default=20, ge=2, le=200)
    multiplier: float = Field(default=2.0, ge=1.0, le=10.0)
