"""Pydantic v2 schemas for user-curated watchlists (Phase 5B).

Mirrors the patterns in ``pipeline_schemas.py`` / ``scanner_schemas.py``:
Create / Update / Response variants; ``from_attributes=True`` for ORM
serialization. Ticker field validators normalize to uppercase.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# UserWatchlist
# ---------------------------------------------------------------------------


class UserWatchlistCreate(BaseModel):
    """Body for ``POST /watchlists`` — name only; tickers start empty."""

    name: str = Field(..., min_length=1, max_length=200)


class UserWatchlistUpdate(BaseModel):
    """Body for ``PATCH /watchlists/{id}`` — partial update."""

    name: str | None = Field(None, min_length=1, max_length=200)
    tickers: list[str] | None = None

    @field_validator("tickers")
    @classmethod
    def _normalize_tickers(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return [t.strip().upper() for t in v if t and t.strip()]


class UserWatchlistResponse(BaseModel):
    """Returned by all watchlist routes."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    tickers: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Ticker add/remove
# ---------------------------------------------------------------------------


class TickerAddRequest(BaseModel):
    """Body for ``POST /watchlists/{id}/tickers``."""

    ticker: str = Field(..., min_length=1, max_length=20)

    @field_validator("ticker")
    @classmethod
    def _upper(cls, v: str) -> str:
        cleaned = v.strip().upper()
        if not cleaned:
            raise ValueError("ticker must be non-empty")
        return cleaned


# ---------------------------------------------------------------------------
# Ticker search (GET /tickers/search)
# ---------------------------------------------------------------------------


class TickerSearchResult(BaseModel):
    """One row in the ticker autocomplete response."""

    ticker: str
    name: str | None = None
