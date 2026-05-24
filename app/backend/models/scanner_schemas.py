"""Pydantic request/response schemas for the scanner REST API.

Pattern mirrors app/backend/models/schemas.py — Request / Response / Summary
variants, validators where useful, `from_attributes = True` for ORM-friendly
serialization.
"""

from datetime import datetime
from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class UniverseKind(str, Enum):
    SP500 = "sp500"
    NASDAQ100 = "nasdaq100"
    NASDAQ100_SP500 = "nasdaq100_sp500"   # recommended default for new configs
    RUSSELL3000 = "russell3000"
    ALL_US = "all_us"
    CUSTOM = "custom"
    WATCHLIST = "watchlist"   # Phase 5C — pick from saved UserWatchlist rows


class ScanStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    ERROR = "ERROR"


class Direction(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


# ---------------------------------------------------------------------------
# ScannerConfig
# ---------------------------------------------------------------------------


class ScannerConfigBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    universe_kind: UniverseKind
    universe_tickers: Optional[List[str]] = Field(
        None, description="Required when universe_kind == 'custom'"
    )
    cron_expr: str = Field("0 21 * * 1-5", description="5-field cron in America/New_York")
    is_enabled: bool = True
    top_n: int = Field(20, ge=1, le=200)
    weights: Optional[dict[str, Any]] = None
    # Phase 5C — required when universe_kind == 'watchlist'; points at the
    # UserWatchlist row whose ``tickers`` list becomes the scan universe.
    user_watchlist_id: Optional[int] = Field(
        None, description="Required when universe_kind == 'watchlist'"
    )

    @model_validator(mode="after")
    def _custom_requires_tickers(self):
        # field_validator on universe_tickers doesn't fire when the field falls
        # back to its default (None) — model_validator runs unconditionally.
        if self.universe_kind == UniverseKind.CUSTOM and not self.universe_tickers:
            raise ValueError("universe_tickers is required when universe_kind='custom'")
        if (
            self.universe_kind == UniverseKind.WATCHLIST
            and self.user_watchlist_id is None
        ):
            raise ValueError(
                "user_watchlist_id is required when universe_kind='watchlist'"
            )
        return self


class ScannerConfigCreateRequest(ScannerConfigBase):
    pass


class ScannerConfigUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    universe_kind: Optional[UniverseKind] = None
    universe_tickers: Optional[List[str]] = None
    cron_expr: Optional[str] = None
    is_enabled: Optional[bool] = None
    top_n: Optional[int] = Field(None, ge=1, le=200)
    weights: Optional[dict[str, Any]] = None
    user_watchlist_id: Optional[int] = None


class ScannerConfigResponse(ScannerConfigBase):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# ScanRun
# ---------------------------------------------------------------------------


class ScanRunSummary(BaseModel):
    id: int
    config_id: int
    status: ScanStatus
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    universe_size: Optional[int] = None
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# WatchlistEntry
# ---------------------------------------------------------------------------


class TriggerPayload(BaseModel):
    """Serialized form of v2.scanner.detectors.base.EventTrigger."""

    detector: str
    triggered: bool = True
    severity_z: float
    direction: Direction = Direction.NEUTRAL
    reason: str
    components: dict[str, float] = Field(default_factory=dict)
    asof_date: Optional[str] = None


class WatchlistEntryResponse(BaseModel):
    id: int
    scan_run_id: int
    ticker: str
    composite_score: float
    direction: Direction
    event_score: float
    quant_score: Optional[float] = None
    # Raw max |severity_z| across triggered detectors — the deterministic
    # tiebreaker for ties at composite_score = 100.
    event_severity: float = 0.0
    triggers: List[TriggerPayload] = Field(default_factory=list)
    rank: int

    class Config:
        from_attributes = True


class ScanRunDetailResponse(ScanRunSummary):
    """Run summary + full Top-N entries — used by GET /scanner/runs/{id}/entries."""

    entries: List[WatchlistEntryResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Live quote response (GET /scanner/runs/{id}/quotes)
# ---------------------------------------------------------------------------


class QuoteResponse(BaseModel):
    """One ticker's live-ish quote, fetched at request time (not persisted)."""

    ticker: str
    current_price: Optional[float] = None
    prev_close: Optional[float] = None
    percent_change: Optional[float] = None
    asof_timestamp: Optional[int] = None


# ---------------------------------------------------------------------------
# Detector metadata (GET /scanner/detectors)
# ---------------------------------------------------------------------------


class DetectorMetadataResponse(BaseModel):
    """One registered detector's UI-facing metadata.

    Surfaced via ``GET /scanner/detectors`` so the frontend dialog can render
    a checkbox-and-slider row per detector without hardcoding labels.
    """

    name: str = Field(..., description="Stable .name attribute used in DB rows + ScannerWeights")
    label: str = Field(..., description="Human-readable display name")
    default_mult: float = Field(..., ge=0.0, le=5.0, description="Recommended severity multiplier")
    description: str = Field(..., description="One-line explanation of what the detector fires on")
