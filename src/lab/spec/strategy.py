"""Phase 6A: top-level StrategySpec with discriminated-union assembly.

LLM emits this via with_structured_output(StrategySpec, method="json_mode").
Pydantic uses the `type` field on each block as the discriminator so
the union dispatches to the right Pydantic model at parse time.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, model_validator

from src.lab.spec.blocks_entry import (
    BollingerBreakEntry, DonchianBreakEntry, MACDEntry, MACrossEntry,
    PriceVsMAEntry, RSICrossEntry, RSIEntry, VolumeSpikeEntry,
)
from src.lab.spec.blocks_exit import (
    StopLossExit, TakeProfitExit, TimeStopExit, TrailingStopExit,
)
from src.lab.spec.blocks_filters import (
    LiquidityFilter, TrendFilter, VolatilityFilter,
)
from src.lab.spec.blocks_sizing import (
    EqualWeightSizing, FixedPctSizing, VolTargetedSizing,
)


# Discriminated unions — Pydantic uses `type` field to dispatch
EntrySpec = Annotated[
    Union[
        RSIEntry, RSICrossEntry, MACrossEntry, PriceVsMAEntry,
        MACDEntry, BollingerBreakEntry, DonchianBreakEntry, VolumeSpikeEntry,
    ],
    Field(discriminator="type"),
]

ExitSpec = Annotated[
    Union[StopLossExit, TakeProfitExit, TrailingStopExit, TimeStopExit],
    Field(discriminator="type"),
]

SizingSpec = Annotated[
    Union[FixedPctSizing, EqualWeightSizing, VolTargetedSizing],
    Field(discriminator="type"),
]

FilterSpec = Annotated[
    Union[TrendFilter, VolatilityFilter, LiquidityFilter],
    Field(discriminator="type"),
]


class UniverseSpec(BaseModel):
    kind: Literal["watchlist", "sp500", "nasdaq100"]
    # required when kind == "watchlist"; None otherwise
    watchlist_id: int | None = None

    @model_validator(mode="after")
    def _watchlist_kind_requires_id(self):
        if self.kind == "watchlist" and self.watchlist_id is None:
            raise ValueError("universe.watchlist_id required when kind='watchlist'")
        return self


class EntryGroup(BaseModel):
    combiner: Literal["and", "or"] = "and"
    signals: list[EntrySpec] = Field(min_length=1, max_length=5)


class BacktestConfig(BaseModel):
    # All Optional; defaults applied if LLM omits
    start_date: str | None = None  # YYYY-MM-DD; default: today - 5y
    end_date: str | None = None    # YYYY-MM-DD; default: today
    is_oos_split: float = Field(default=0.7, ge=0.3, le=0.9)
    starting_capital_usd: float = Field(default=100_000, gt=0)
    commission_bps: float = Field(default=5, ge=0, le=100)
    slippage_bps: float = Field(default=5, ge=0, le=100)
    max_concurrent_positions: int = Field(default=10, ge=1, le=100)
    benchmark: Literal["spy", "none"] = "spy"
    reverse_signal_as_exit: bool = True
    full_position_policy: Literal["skip", "replace_weakest"] = "skip"


class StrategySpec(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    universe: UniverseSpec
    entry: EntryGroup
    exit: list[ExitSpec] = Field(min_length=1, max_length=5)
    filters: list[FilterSpec] = Field(default_factory=list, max_length=5)
    sizing: SizingSpec
    backtest_config: BacktestConfig = Field(default_factory=BacktestConfig)
