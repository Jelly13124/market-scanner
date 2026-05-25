"""Phase 6A: 4 exit signal block Pydantic models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class StopLossExit(BaseModel):
    type: Literal["stop_loss"] = "stop_loss"
    mode: Literal["pct", "atr"] = "pct"
    value: float = Field(gt=0)  # pct: 0.05 = 5%; atr: 2.0 = 2 x ATR(14)


class TakeProfitExit(BaseModel):
    type: Literal["take_profit"] = "take_profit"
    pct: float = Field(ge=0, le=10)  # 0.10 = +10% from entry


class TrailingStopExit(BaseModel):
    type: Literal["trailing_stop"] = "trailing_stop"
    mode: Literal["pct", "atr"] = "pct"
    value: float = Field(gt=0)


class TimeStopExit(BaseModel):
    type: Literal["time_stop"] = "time_stop"
    bars: int = Field(default=20, ge=1, le=500)
