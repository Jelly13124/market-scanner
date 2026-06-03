"""/screener REST endpoints.

  GET /screener/snapshot/latest    — filtered query (chip-driven)
  GET /screener/snapshot/columns   — static chip metadata
  GET /screener/snapshot/status    — last-built timestamp + per-market counts
  GET /screener/sectors            — per-sector summary for the Sectors board
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Annotated

from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backend.auth.dependencies import get_current_user
from app.backend.database import get_db
from app.backend.database.models import TickerSnapshot, User
from app.backend.models.screener_schemas import (
    ScreenerColumnMetadata,
    ScreenerSnapshotResponse,
    ScreenerStatusResponse,
    SectorSummaryRow,
    SnapshotRefreshOut,
    SnapshotRefreshStateOut,
    SnapshotRowOut,
)
from app.backend.models.screener_preset_schemas import PresetCreate, PresetOut, PresetPatch
from app.backend.repositories.screener_preset_repository import ScreenerPresetRepository
from app.backend.repositories.screener_repository import ScreenerRepository
from app.backend.services.scheduler_service import SchedulerService, get_scheduler_service
from app.backend.services.snapshot_refresh import get_refresh_state, start_refresh
from src.screener.column_metadata import COLUMN_METADATA

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/screener")


_RESERVED_QUERY_KEYS = {"market", "sort_by", "sort_dir", "limit", "offset"}


def _parse_filters(request: Request) -> dict:
    """Pull every non-reserved query param into the filters dict.
    Multi-value 'sector_in' / 'analyst_rating_in' are CSV-split.
    """
    filters: dict = {}
    for k, v in request.query_params.multi_items():
        if k in _RESERVED_QUERY_KEYS:
            continue
        if k.endswith("_in"):
            filters[k] = [x.strip() for x in v.split(",") if x.strip()]
        else:
            filters[k] = v
    return filters


@router.get("/snapshot/latest", response_model=ScreenerSnapshotResponse)
def get_latest_snapshot(
    request: Request,
    market: Annotated[str | None, Query(pattern="^(US|CN|ALL)$")] = None,
    sort_by: str = "market_cap",
    sort_dir: str = "desc",
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> ScreenerSnapshotResponse:
    repo = ScreenerRepository(db)

    market_list: list[str] | None
    if market is None or market == "ALL":
        market_list = None
    else:
        market_list = [market]

    filters = _parse_filters(request)
    rows, total = repo.query(
        market=market_list,
        filters=filters,
        sort_by=sort_by,
        sort_dir=sort_dir if sort_dir in ("asc", "desc") else "desc",
        limit=limit,
        offset=offset,
    )

    if rows:
        snapshot_date = rows[0].snapshot_date
        last_updated = max((r.last_updated for r in rows if r.last_updated),
                           default=datetime.now(timezone.utc))
    else:
        snapshot_date = repo.latest_snapshot_date(
            market=market_list[0] if market_list and len(market_list) == 1 else None,
        ) or date.today()
        last_updated = datetime.now(timezone.utc)

    return ScreenerSnapshotResponse(
        rows=[SnapshotRowOut.model_validate(r) for r in rows],
        total_count=total,
        snapshot_date=snapshot_date,
        last_updated=last_updated,
    )


@router.get("/snapshot/columns", response_model=ScreenerColumnMetadata)
def get_column_metadata() -> ScreenerColumnMetadata:
    return ScreenerColumnMetadata(columns=COLUMN_METADATA)


@router.get("/snapshot/status", response_model=ScreenerStatusResponse)
def get_snapshot_status(db: Session = Depends(get_db)) -> ScreenerStatusResponse:
    repo = ScreenerRepository(db)
    snapshot_date = repo.latest_snapshot_date()

    row_count = 0
    by_market: dict[str, int] = {}
    last_updated: datetime | None = None
    if snapshot_date is not None:
        result = db.execute(
            select(TickerSnapshot.market, func.count(), func.max(TickerSnapshot.last_updated))
            .where(TickerSnapshot.snapshot_date == snapshot_date)
            .group_by(TickerSnapshot.market)
        ).all()
        for mkt, n, lu in result:
            by_market[mkt] = int(n)
            row_count += int(n)
            if lu is not None and (last_updated is None or lu > last_updated):
                last_updated = lu

    return ScreenerStatusResponse(
        snapshot_date=snapshot_date,
        last_updated=last_updated,
        row_count=row_count,
        by_market=by_market,
    )


@router.get("/sectors", response_model=list[SectorSummaryRow])
def get_sector_summary(
    market: Annotated[str, Query(pattern="^(US|CN)$")] = "US",
    db: Session = Depends(get_db),
) -> list[SectorSummaryRow]:
    """Per-sector summary of the latest snapshot — PUBLIC (global market data)."""
    return [SectorSummaryRow(**r) for r in ScreenerRepository(db).sector_summary(market)]


@router.post("/snapshot/refresh", response_model=SnapshotRefreshOut)
def refresh_snapshot(
    market: Annotated[str, Query(pattern="^(US|CN)$")] = "US",
) -> SnapshotRefreshOut:
    """Trigger a single-market snapshot rebuild on a background thread.

    Returns immediately. ``started=False`` means a refresh was already in
    flight; poll GET /snapshot/refresh for progress either way.
    """
    try:
        started, state = start_refresh(market)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return SnapshotRefreshOut(started=started, state=SnapshotRefreshStateOut(**state))


@router.get("/snapshot/refresh", response_model=SnapshotRefreshStateOut)
def snapshot_refresh_status() -> SnapshotRefreshStateOut:
    return SnapshotRefreshStateOut(**get_refresh_state())


def _validate_cron(expr: str) -> None:
    """400 on an invalid cron expression (mirrors report_schedules)."""
    try:
        CronTrigger.from_crontab(expr)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, f"Invalid cron expression: {expr!r}") from e


@router.get("/presets", response_model=list[PresetOut])
def list_presets(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PresetOut]:
    return [PresetOut.model_validate(p) for p in ScreenerPresetRepository(db).list(user_id=current_user.id)]


@router.post("/presets", response_model=PresetOut, status_code=status.HTTP_201_CREATED)
def create_preset(
    body: PresetCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scheduler: SchedulerService = Depends(get_scheduler_service),
) -> PresetOut:
    _validate_cron(body.cron_expr)
    p = ScreenerPresetRepository(db).create(
        name=body.name, market=body.market, filters=body.filters,
        sort_by=body.sort_by, sort_dir=body.sort_dir,
        schedule_enabled=body.schedule_enabled, cron_expr=body.cron_expr,
        notify_channels=body.notify_channels,
        user_id=current_user.id,
    )
    try:
        scheduler.register_screener_preset(p)
    except Exception as e:
        logger.warning("register screener preset %s failed: %s", p.id, e)
    return PresetOut.model_validate(p)


@router.patch("/presets/{preset_id}", response_model=PresetOut)
def patch_preset(
    preset_id: int,
    body: PresetPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scheduler: SchedulerService = Depends(get_scheduler_service),
) -> PresetOut:
    if body.cron_expr is not None:
        _validate_cron(body.cron_expr)
    p = ScreenerPresetRepository(db).patch(preset_id, body.model_dump(exclude_unset=True), user_id=current_user.id)
    if p is None:
        raise HTTPException(404, f"No preset {preset_id}")
    try:
        scheduler.register_screener_preset(p)
    except Exception as e:
        logger.warning("re-register screener preset %s failed: %s", p.id, e)
    return PresetOut.model_validate(p)


@router.delete("/presets/{preset_id}", status_code=204)
def delete_preset(
    preset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scheduler: SchedulerService = Depends(get_scheduler_service),
) -> Response:
    if not ScreenerPresetRepository(db).delete(preset_id, user_id=current_user.id):
        raise HTTPException(404, f"No preset {preset_id}")
    try:
        scheduler.unregister_screener_preset(preset_id)
    except Exception as e:
        logger.warning("unregister screener preset %s failed: %s", preset_id, e)
    return Response(status_code=204)


@router.post("/presets/{preset_id}/run", response_model=ScreenerSnapshotResponse)
def run_preset(
    preset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ScreenerSnapshotResponse:
    repo = ScreenerPresetRepository(db)
    p = repo.get(preset_id, user_id=current_user.id)
    if p is None:
        raise HTTPException(404, f"No preset {preset_id}")
    screener = ScreenerRepository(db)
    market_list = [p.market] if p.market else None
    rows, total = screener.query(
        market=market_list, filters=p.filters_json or {},
        sort_by=p.sort_by, sort_dir=p.sort_dir, limit=200,
    )
    snap_date = rows[0].snapshot_date if rows else (
        screener.latest_snapshot_date() or date.today())
    last_updated = max((r.last_updated for r in rows if r.last_updated),
                       default=datetime.now(timezone.utc))
    return ScreenerSnapshotResponse(
        rows=[SnapshotRowOut.model_validate(r) for r in rows],
        total_count=total, snapshot_date=snap_date, last_updated=last_updated,
    )
