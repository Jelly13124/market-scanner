"""Pydantic schemas for /screener/presets."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class PresetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    market: Literal["US", "CN"] | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    sort_by: str = "market_cap"
    sort_dir: Literal["asc", "desc"] = "desc"
    schedule_enabled: bool = False
    notify_channels: list[Literal["email", "webhook"]] | None = None


class PresetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    market: Literal["US", "CN"] | None = None
    filters: dict[str, Any] | None = None
    sort_by: str | None = None
    sort_dir: Literal["asc", "desc"] | None = None
    schedule_enabled: bool | None = None
    notify_channels: list[Literal["email", "webhook"]] | None = None


class PresetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    market: str | None
    filters: dict[str, Any] = Field(validation_alias="filters_json")
    sort_by: str
    sort_dir: str
    schedule_enabled: bool
    notify_channels: list[str] | None
    last_run_at: datetime | None
    last_match_count: int | None
