"""Phase 6E: Pydantic schemas for /lab/* REST routes."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ---- Strategy ----

class StrategyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    # If omitted, server creates an empty-spec scaffold the user fills via chat
    initial_spec_json: dict | None = None


class StrategyUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    spec_json: dict | None = None  # manual edit path (bypasses AI)


class StrategyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str | None
    spec_json: dict
    version: int
    created_at: datetime
    updated_at: datetime | None


# ---- Chat ----

class ChatSendRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ChatMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    strategy_id: int
    created_at: datetime
    role: str
    content: str
    spec_snapshot_json: dict | None = None
    spec_patch_json: dict | None = None
    patch_accepted: bool | None = None


class ChatResponse(BaseModel):
    """Returned from POST /lab/strategies/{id}/chat — combines new AI message
    + (if AI proposed a patch) the resulting spec preview."""
    message: ChatMessageResponse
    kind: Literal["reply", "patch"]
    proposed_spec_json: dict | None = None  # the NEW spec if accepted; null for replies


class ChatApplyRequest(BaseModel):
    message_id: int


# ---- Backtest ----

class BacktestRunRequest(BaseModel):
    """No body required — server uses the strategy's current spec.
    Future: allow ad-hoc overrides without committing to spec."""
    pass  # explicit empty body model


class BacktestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    strategy_id: int
    created_at: datetime
    spec_snapshot_json: dict
    start_date: str
    end_date: str
    midpoint_date: str
    universe_size: int

    is_total_return: float | None
    is_cagr: float | None
    is_sharpe: float | None
    is_sortino: float | None
    is_max_drawdown: float | None
    is_calmar: float | None
    is_win_rate: float | None
    is_profit_factor: float | None
    is_n_trades: int | None
    is_avg_holding_days: float | None

    oos_total_return: float | None
    oos_cagr: float | None
    oos_sharpe: float | None
    oos_sortino: float | None
    oos_max_drawdown: float | None
    oos_calmar: float | None
    oos_win_rate: float | None
    oos_profit_factor: float | None
    oos_n_trades: int | None
    oos_avg_holding_days: float | None

    degradation_ratio: float | None
    benchmark_cagr: float | None
    verdict_label: str
    verdict_text: str

    trades_json: list
    equity_curve_is: list
    equity_curve_oos: list
    benchmark_curve: list | None
    duration_seconds: float | None
    error_message: str | None
