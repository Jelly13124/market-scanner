"""Pydantic schemas for /screener endpoints. Mirrors TickerSnapshot
fields 1:1 (minus `id` and `last_updated`).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


class SnapshotRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    market: str
    snapshot_date: date

    price: Decimal | None = None
    prev_close: Decimal | None = None
    change_pct: Decimal | None = None
    volume: int | None = None
    avg_volume_10d: int | None = None
    rel_volume: Decimal | None = None

    market_cap: Decimal | None = None

    pe_ttm: Decimal | None = None
    pe_forward: Decimal | None = None
    pb: Decimal | None = None
    ps: Decimal | None = None
    peg: Decimal | None = None

    eps_growth_yoy: Decimal | None = None
    revenue_growth_yoy: Decimal | None = None

    roe: Decimal | None = None
    profit_margin: Decimal | None = None

    dividend_yield_pct: Decimal | None = None
    beta: Decimal | None = None

    sector: str | None = None
    industry: str | None = None
    exchange: str | None = None

    analyst_rating: str | None = None
    analyst_count: int | None = None
    target_mean_price: Decimal | None = None

    recent_earnings_date: date | None = None
    upcoming_earnings_date: date | None = None

    perf_1d: Decimal | None = None
    perf_5d: Decimal | None = None
    perf_1m: Decimal | None = None
    perf_3m: Decimal | None = None
    perf_ytd: Decimal | None = None
    perf_1y: Decimal | None = None

    data_source: str | None = None


class LiveQuoteRow(BaseModel):
    source: str | None = None
    source_timestamp: int | None = None
    received_at: str | None = None
    """One live (on-demand) market quote for a watchlist ticker.

    All numeric fields are nullable so the UI can render "—" when a symbol
    has no data (``error`` populated in that case).
    """

    ticker: str
    price: float | None = None
    prev_close: float | None = None
    change_pct: float | None = None
    volume: int | None = None
    day_open: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    error: str | None = None


class SectorMover(BaseModel):
    ticker: str
    change_pct: Decimal | None = None


class SectorSummaryRow(BaseModel):
    sector: str
    count: int
    avg_change_pct: Decimal | None = None
    gainers: int
    losers: int
    total_market_cap: Decimal | None = None
    top_gainer: SectorMover | None = None
    top_loser: SectorMover | None = None


class ScreenerSnapshotResponse(BaseModel):
    rows: list[SnapshotRowOut]
    total_count: int
    snapshot_date: date
    last_updated: datetime


class ScreenerSelectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    watchlist_id: int | None = Field(default=None, gt=0)
    new_watchlist_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] | None = None
    market: Literal["US", "CN", "ALL"]
    snapshot_date: date
    filters: dict[str, str | int | float | list[str] | None]
    tickers: list[Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=20)]] = Field(min_length=1)

    @model_validator(mode="after")
    def check_watchlist(self) -> Self:
        if (self.watchlist_id is None) == (self.new_watchlist_name is None):
            raise ValueError("Choose an existing watchlist or give a new watchlist name")
        return self


class UniverseSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    origin: str
    market: str
    tickers: list[str]
    filters: dict | None
    filter_version: str | None
    screener_snapshot_date: date | None
    selected_at: datetime
    source_watchlist_id: int | None
    source_snapshot_id: int | None


class ScreenerStatusResponse(BaseModel):
    snapshot_date: date | None
    last_updated: datetime | None
    row_count: int
    by_market: dict[str, int]


class ScreenerColumnMetadata(BaseModel):
    columns: list[dict[str, Any]]


class SnapshotRefreshStateOut(BaseModel):
    """Progress/state of an on-demand snapshot rebuild (polled by the UI)."""

    running: bool
    market: str | None = None
    done: int = 0
    total: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    inserted: int | None = None
    error: str | None = None


class SnapshotRefreshOut(BaseModel):
    """Response to POST /snapshot/refresh. ``started=False`` ⇒ already running."""

    started: bool
    state: SnapshotRefreshStateOut
