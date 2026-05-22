"""Pydantic request/response schemas for the research REST API.

Wrappers around the internal src.research.models dataclasses. The internal
types stay dataclasses (no Pydantic overhead in the pipeline hot path);
these schemas are the API boundary types.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# Mirror the Literal types from src/research/models.py
HoldingStatus = Literal["holding", "watching", "considering_buy", "considering_short"]
RiskTolerance = Literal["conservative", "moderate", "aggressive"]
ReportGoal = Literal["new_entry", "hold_review", "exit_decision", "general_research"]
Direction = Literal["long", "short", "stand_aside"]
SampleQuality = Literal["strong", "moderate", "weak", "insufficient"]


class ResearchRunRequest(BaseModel):
    """POST /research/run body. Defaults mirror the CLI's defaults so
    on-demand callers can fire-and-forget with just a ticker."""

    ticker: str
    holding_status: HoldingStatus = "watching"
    target_position_pct: float = Field(default=0.05, ge=0.0, le=1.0)
    risk_tolerance: RiskTolerance = "moderate"
    report_goal: ReportGoal = "general_research"
    use_personas: bool = False

    @field_validator("ticker")
    @classmethod
    def _uppercase_ticker(cls, v: str) -> str:
        return v.strip().upper()


class TradePlanPayload(BaseModel):
    """API mirror of src.research.models.TradePlan."""

    direction: Direction
    entry_price: float | None
    target_price: float | None
    stop_price: float | None
    horizon_days: int = Field(ge=0)
    sizing_pct: float = Field(ge=0.0, le=1.0)
    confidence: int = Field(ge=0, le=100)
    rationale: str


class BacktestSummaryPayload(BaseModel):
    """API mirror of src.research.models.BacktestSummary."""

    matches_found: int = Field(ge=0)
    win_rate: float | None
    avg_pnl_pct: float | None
    max_drawdown_pct: float | None
    avg_holding_days: float | None
    sample_quality: SampleQuality
    caveat: str | None


class ResearchReportSummary(BaseModel):
    """List-mode response - one row per report, no body content."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    scan_date: str
    created_at: datetime
    use_personas: bool
    duration_seconds: float | None


class ResearchReportDetail(BaseModel):
    """Full report including markdown body, plan, and backtest. The
    rendered_html field is fetched separately via /reports/{id}/html
    to keep the JSON response light when the consumer only wants the
    structured data."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    scan_date: str
    created_at: datetime
    use_personas: bool
    persona_assignments: dict | None
    report_markdown: str
    duration_seconds: float | None
    plan: TradePlanPayload
    backtest: BacktestSummaryPayload
