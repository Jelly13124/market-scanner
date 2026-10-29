"""Pydantic schemas for the AnalyzeFlow REST endpoints (Phase 5D)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AnalyzeFlowCreate(BaseModel):
    """POST /analyze-flows body."""

    name: str = Field(min_length=1, max_length=200)
    included_sections: list[str] = Field(default_factory=list)
    use_personas: bool = False
    debate_rounds: int = Field(default=1, ge=1, le=5)
    persona_overrides: dict[str, str] | None = None


class AnalyzeFlowUpdate(BaseModel):
    """PATCH /analyze-flows/{id} body — all fields optional."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    included_sections: list[str] | None = None
    use_personas: bool | None = None
    debate_rounds: int | None = Field(default=None, ge=1, le=5)
    persona_overrides: dict[str, str] | None = None


class AnalyzeFlowResponse(BaseModel):
    """Standard read shape."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    included_sections: list[str]
    use_personas: bool
    debate_rounds: int
    persona_overrides: dict[str, str] | None = None
    created_at: datetime
    updated_at: datetime | None = None
