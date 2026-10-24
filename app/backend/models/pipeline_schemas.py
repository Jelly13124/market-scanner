"""Pydantic request/response schemas for the scanner→agent pipeline REST API.

Pattern mirrors ``app/backend/models/scanner_schemas.py`` — Request /
Response / Summary variants with ``from_attributes = True`` for ORM
serialization.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PipelineStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    ERROR = "ERROR"


# ---------------------------------------------------------------------------
# POST /pipeline/run
# ---------------------------------------------------------------------------


class RunPipelineRequest(BaseModel):
    """Body for ``POST /pipeline/run``.

    Either ``template`` (named roster) or ``custom_analysts`` (explicit
    list) — not both. Leaving both unset defaults to the ``balanced``
    template.
    """

    scan_date: str | None = Field(
        None,
        description="ISO YYYY-MM-DD; defaults to the latest trading day ≤ today.",
    )
    universe: str = Field(
        "nasdaq100",
        description="'sp500' | 'nasdaq100' | 'nasdaq100_sp500' | 'russell3000' | 'all_us' | 'custom'",
    )
    universe_tickers: list[str] | None = Field(
        None, description="Required when universe == 'custom'"
    )
    top_n: int = Field(5, ge=1, le=50, description="Watchlist size passed to agents.")
    template: str | None = Field(
        None,
        description="Named analyst roster ('balanced'|'value'|'growth'|'quick'). Mutually exclusive with custom_analysts.",
    )
    custom_analysts: list[str] | None = Field(
        None,
        description="Explicit analyst-key list. 'scanner_signal' auto-prepended.",
    )
    model_name: str = Field("gpt-4.1", description="LLM model name.")
    model_provider: str = Field("OpenAI", description="LLM provider key.")
    portfolio: dict[str, Any] | None = Field(
        None,
        description="Starting portfolio dict; defaults to $100k cash long-only.",
    )

    @model_validator(mode="after")
    def _exclusive_template_or_custom(self):
        if self.template is not None and self.custom_analysts is not None:
            raise ValueError(
                "pass either template OR custom_analysts, not both"
            )
        if self.universe == "custom" and not self.universe_tickers:
            raise ValueError(
                "universe_tickers is required when universe == 'custom'"
            )
        return self


class RunPipelineResponse(BaseModel):
    """Immediate response to POST /pipeline/run — the actual work
    runs in a FastAPI BackgroundTask."""

    run_id: str
    status: PipelineStatus


# ---------------------------------------------------------------------------
# GET /pipeline/runs[/{id}]
# ---------------------------------------------------------------------------


class PipelineRunSummary(BaseModel):
    """List-page row — no JSON blobs."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime | None = None
    completed_at: datetime | None = None
    scan_date: str
    template: str
    top_n: int
    universe: str
    status: PipelineStatus
    duration_seconds: float | None = None
    error: str | None = None


class PipelineRunDetail(PipelineRunSummary):
    """Full run including JSON blobs (heavier — only fetched per-id)."""

    selected_analysts: list[str]
    watchlist: list[dict[str, Any]] | None = None
    agent_decisions: dict[str, Any] | None = None
    analyst_signals: dict[str, dict[str, dict[str, Any]]] | None = None


# ---------------------------------------------------------------------------
# GET /pipeline/templates
# ---------------------------------------------------------------------------


class AgentMetadata(BaseModel):
    """One row in the agents metadata payload — mirrors
    src.utils.analysts.get_agents_list()."""

    key: str
    display_name: str
    description: str
    investing_style: str
    order: int


class TemplatesResponse(BaseModel):
    """Returned by GET /pipeline/templates — feeds the UI 'analyze' modal."""

    templates: dict[str, list[str]]
    default_template: str
    agents: list[AgentMetadata]


# ---------------------------------------------------------------------------
# /pipeline/schedule  (simple GET + PATCH)
# ---------------------------------------------------------------------------


class PipelineScheduleResponse(BaseModel):
    """Single-row config for the daily cron pipeline."""

    model_config = ConfigDict(from_attributes=True)

    enabled: bool
    top_n: int
    template: str
    universe: str
    model_name: str
    model_provider: str
    updated_at: datetime | None = None


class PipelineScheduleUpdateRequest(BaseModel):
    """All fields optional — patch semantics."""

    enabled: bool | None = None
    top_n: int | None = Field(None, ge=1, le=50)
    template: str | None = None
    universe: str | None = None
    model_name: str | None = None
    model_provider: str | None = None
