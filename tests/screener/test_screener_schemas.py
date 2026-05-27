"""Pydantic schema smoke."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal


def test_snapshot_row_out_construction():
    from app.backend.models.screener_schemas import SnapshotRowOut
    out = SnapshotRowOut(
        ticker="AAPL", market="US", snapshot_date=date(2026, 5, 27),
        price=Decimal("210.50"), market_cap=Decimal("3.2e12"),
        sector="Technology",
    )
    payload = out.model_dump()
    assert payload["ticker"] == "AAPL"
    assert payload["pe_ttm"] is None


def test_snapshot_response_envelope():
    from app.backend.models.screener_schemas import (
        ScreenerSnapshotResponse, SnapshotRowOut,
    )
    resp = ScreenerSnapshotResponse(
        rows=[],
        total_count=0,
        snapshot_date=date(2026, 5, 27),
        last_updated=datetime.utcnow(),
    )
    assert resp.total_count == 0


def test_status_response():
    from app.backend.models.screener_schemas import ScreenerStatusResponse
    s = ScreenerStatusResponse(
        snapshot_date=date(2026, 5, 27),
        last_updated=datetime.utcnow(),
        row_count=800,
        by_market={"US": 500, "CN": 300},
    )
    assert s.by_market["US"] == 500
