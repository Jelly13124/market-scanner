"""Persistable definitions of the shared daily price and volume rules."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class DailyRule(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    type: str
    version: Literal["1"] = "1"
    window: int = Field(default=20, ge=1)
    direction: Literal["bullish", "bearish", "neutral", "any"] = "bullish"


class RelativeVolumeRule(DailyRule):
    type: Literal["relative_volume"] = "relative_volume"
    threshold: float = Field(default=2.0, gt=1)


class RangeBreakoutRule(DailyRule):
    type: Literal["range_breakout"] = "range_breakout"


class RelativeStrengthRule(DailyRule):
    type: Literal["relative_strength"] = "relative_strength"
    threshold: float = Field(default=0.05, gt=0)


DailyCondition = Annotated[
    RelativeVolumeRule | RangeBreakoutRule | RelativeStrengthRule,
    Field(discriminator="type"),
]
Combiner = Literal["and", "or"]


class RuleGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    combiner: Combiner
    signals: list[DailyCondition] = Field(min_length=1)
