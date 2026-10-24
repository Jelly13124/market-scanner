"""Scanner REST API.

Endpoints:
    GET    /scanner/configs                  list caller's configs
    POST   /scanner/configs                  create + register cron (owned by caller)
    GET    /scanner/configs/{id}             get one (404 if not owned by caller)
    PATCH  /scanner/configs/{id}             update + reschedule cron (scoped)
    DELETE /scanner/configs/{id}             delete + unregister cron (scoped)
    POST   /scanner/configs/{id}/run         trigger manual scan -> {run_id} (scoped)
    GET    /scanner/runs/{run_id}            run status summary (scoped via config owner)
    GET    /scanner/runs/{run_id}/entries    full ranked watchlist for run (scoped)
    GET    /scanner/runs/{run_id}/quotes     live quotes for that run's tickers (scoped)
    GET    /scanner/runs/{run_id}/stream     SSE proxy of live progress

Wave 4 (Task 4.2): all config CRUD + run endpoints require a Bearer token
and are scoped to the caller's ``user_id``. Scan-run reads are scoped via
the parent config's ownership (ScanRun has no user_id column; ownership is
inferred through config_id → ScannerConfig.user_id). WatchlistEntry is
scoped the same way (via scan_run → config → user_id).

The ``/run`` endpoint dispatches the scan onto a background thread and returns
``run_id`` immediately; clients then subscribe to ``/runs/{run_id}/stream``
for live progress events.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.backend.auth.dependencies import get_current_user
from app.backend.database import get_db
from app.backend.database.models import User
from app.backend.rate_limit import heavy_limit, rate_limited
from app.backend.models.scanner_schemas import (
    DetectorMetadataResponse,
    QuoteResponse,
    ScanRunDetailResponse,
    ScanRunSummary,
    ScannerConfigCreateRequest,
    ScannerConfigResponse,
    ScannerConfigUpdateRequest,
)
from app.backend.repositories.scanner_repository import (
    ScanRunRepository,
    ScannerConfigRepository,
    WatchlistEntryRepository,
)
from app.backend.services.scan_broadcaster import ScanBroadcaster, get_broadcaster
from app.backend.services.scanner_service import ScanAlreadyRunningError
from app.backend.services.scheduler_service import (
    SchedulerService,
    get_scheduler_service,
)
from v2.data.factory import make_data_client, recommend_max_workers
from v2.scanner.detectors import ALL_DETECTORS, DETECTOR_METADATA

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scanner")


# ----------------------------------------------------------------------
# Detector metadata (for the config dialog's per-detector picker)
# ----------------------------------------------------------------------


@router.get("/detectors", response_model=list[DetectorMetadataResponse])
def list_detectors() -> list[DetectorMetadataResponse]:
    """Registered detectors and their UI metadata.

    The frontend uses this to render the picker without hardcoding labels.
    Order mirrors ``ALL_DETECTORS`` so the dialog row order is stable.
    """
    out: list[DetectorMetadataResponse] = []
    for cls in ALL_DETECTORS:
        name = cls().name
        meta = DETECTOR_METADATA.get(name)
        if meta is None:
            # Detector with no metadata entry — fall back to bare name so the
            # endpoint never breaks if a detector ships before its metadata.
            out.append(
                DetectorMetadataResponse(
                    name=name,
                    label=name,
                    default_mult=1.0,
                    description="(no description registered)",
                )
            )
        else:
            out.append(
                DetectorMetadataResponse(
                    name=name,
                    label=meta["label"],
                    default_mult=float(meta["default_mult"]),
                    description=meta["description"],
                )
            )
    return out


# ----------------------------------------------------------------------
# ScannerConfig CRUD
# ----------------------------------------------------------------------


@router.get("/configs", response_model=list[ScannerConfigResponse])
def list_configs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ScannerConfigResponse]:
    rows = ScannerConfigRepository(db).list_for_user(user_id=current_user.id)
    return [ScannerConfigResponse.model_validate(r) for r in rows]


@router.post(
    "/configs",
    response_model=ScannerConfigResponse,
    status_code=201,
)
def create_config(
    body: ScannerConfigCreateRequest,
    db: Session = Depends(get_db),
    scheduler: SchedulerService = Depends(get_scheduler_service),
    current_user: User = Depends(get_current_user),
) -> ScannerConfigResponse:
    _validate_cron(body.cron_expr)
    cfg = ScannerConfigRepository(db).create(
        name=body.name,
        universe_kind=body.universe_kind.value,
        universe_tickers=body.universe_tickers,
        cron_expr=body.cron_expr,
        is_enabled=body.is_enabled,
        top_n=body.top_n,
        weights=body.weights,
        user_watchlist_id=body.user_watchlist_id,
        auto_sop_top_n=body.auto_sop_top_n,
        auto_sop_use_personas=body.auto_sop_use_personas,
        email_watchlist=body.email_watchlist,
        email_reports=body.email_reports,
        user_id=current_user.id,
    )
    try:
        scheduler.register_config(cfg)
    except Exception as e:
        logger.exception("Failed to register cron for new config %s", cfg.id)
        raise HTTPException(500, f"Config saved but cron registration failed: {e}")
    return ScannerConfigResponse.model_validate(cfg)


@router.get("/configs/{config_id}", response_model=ScannerConfigResponse)
def get_config(
    config_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ScannerConfigResponse:
    cfg = ScannerConfigRepository(db).get_by_id(config_id, user_id=current_user.id)
    if not cfg:
        raise HTTPException(404, f"No scanner config with id {config_id}")
    return ScannerConfigResponse.model_validate(cfg)


@router.patch("/configs/{config_id}", response_model=ScannerConfigResponse)
def update_config(
    config_id: int,
    body: ScannerConfigUpdateRequest,
    db: Session = Depends(get_db),
    scheduler: SchedulerService = Depends(get_scheduler_service),
    current_user: User = Depends(get_current_user),
) -> ScannerConfigResponse:
    if body.cron_expr is not None:
        _validate_cron(body.cron_expr)
    updates = body.model_dump(exclude_unset=True)
    # Pydantic enum → str
    if "universe_kind" in updates and updates["universe_kind"] is not None:
        updates["universe_kind"] = updates["universe_kind"].value
    # Distinguish "omitted" from "explicit None" for user_watchlist_id
    # (the repo uses this to know whether to overwrite an existing FK).
    if "user_watchlist_id" in updates:
        updates["_set_watchlist_id"] = True
    cfg = ScannerConfigRepository(db).update(config_id, user_id=current_user.id, **updates)
    if not cfg:
        raise HTTPException(404, f"No scanner config with id {config_id}")
    try:
        scheduler.reschedule_config(cfg)
    except Exception as e:
        logger.exception("Failed to reschedule cron for config %s", config_id)
        raise HTTPException(500, f"Config updated but cron reschedule failed: {e}")
    return ScannerConfigResponse.model_validate(cfg)


@router.delete("/configs/{config_id}", status_code=204, response_class=Response)
def delete_config(
    config_id: int,
    db: Session = Depends(get_db),
    scheduler: SchedulerService = Depends(get_scheduler_service),
    current_user: User = Depends(get_current_user),
):
    if not ScannerConfigRepository(db).delete(config_id, user_id=current_user.id):
        raise HTTPException(404, f"No scanner config with id {config_id}")
    scheduler.unregister_config(config_id)
    return Response(status_code=204)


# ----------------------------------------------------------------------
# Manual run + run-status
# ----------------------------------------------------------------------


@router.post("/configs/{config_id}/run", status_code=202)
@rate_limited(heavy_limit())
def run_config_now(
    config_id: int,
    request: Request,
    send_email: bool = False,
    db: Session = Depends(get_db),
    scheduler: SchedulerService = Depends(get_scheduler_service),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Trigger a manual scan and return ``{run_id}`` immediately.

    ``scheduler.run_now`` delegates to ``ScannerService.execute_async`` which
    creates the PENDING ScanRun row synchronously, returns its id, and runs
    the actual scan on a daemon thread. Clients should subscribe to
    ``/scanner/runs/{run_id}/stream`` for live progress.

    ``send_email`` (query param, default False) makes manual delivery opt-in:
    only when ``?send_email=true`` does the post-scan workflow email the
    watchlist/reports to the user's verified recipients (still subject to the
    config's ``email_watchlist``/``email_reports`` flags). A plain manual run
    does NOT email. Cron runs deliver unconditionally via ``execute``.
    """
    if not ScannerConfigRepository(db).get_by_id(config_id, user_id=current_user.id):
        raise HTTPException(404, f"No scanner config with id {config_id}")
    try:
        run_id = scheduler.run_now(config_id, deliver_emails=send_email)
    except ScanAlreadyRunningError as e:
        # Idempotent: a run is already in flight for this config. Return it so the
        # client re-attaches to its stream instead of seeing a 500.
        return {"run_id": e.run_id, "status": "RUNNING", "already_running": True}
    except Exception as e:
        logger.exception("Manual run for config %s failed to dispatch", config_id)
        raise HTTPException(500, str(e))
    return {"run_id": run_id, "status": "RUNNING", "already_running": False}


@router.get("/configs/{config_id}/latest-run", response_model=ScanRunSummary | None)
def get_latest_run_for_config(
    config_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ScanRunSummary | None:
    """Most recent run for a config (any status), or null if none.

    The Scanner panel calls this on mount / config-switch to re-attach to a run
    that is still RUNNING (its live progress lives on the server, not the panel
    that unmounted on a tab switch) or to restore the last run's results. Scoped
    to the config owner.
    """
    if not ScannerConfigRepository(db).get_by_id(config_id, user_id=current_user.id):
        raise HTTPException(404, f"No scanner config with id {config_id}")
    run = ScanRunRepository(db).get_latest_for_config(config_id)
    return ScanRunSummary.model_validate(run) if run else None


@router.get("/runs/{run_id}", response_model=ScanRunSummary)
def get_run(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ScanRunSummary:
    run = ScanRunRepository(db).get_by_id_for_user(run_id, user_id=current_user.id)
    if not run:
        raise HTTPException(404, f"No scan run with id {run_id}")
    return ScanRunSummary.model_validate(run)


@router.get("/runs/{run_id}/entries", response_model=ScanRunDetailResponse)
def get_run_entries(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ScanRunDetailResponse:
    run = ScanRunRepository(db).get_by_id_for_user(run_id, user_id=current_user.id)
    if not run:
        raise HTTPException(404, f"No scan run with id {run_id}")
    entries = WatchlistEntryRepository(db).list_for_run(run_id)
    return ScanRunDetailResponse(
        id=run.id,
        config_id=run.config_id,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        universe_size=run.universe_size,
        error_message=run.error_message,
        created_at=run.created_at,
        entries=entries,
    )


@router.get("/runs/{run_id}/quotes", response_model=dict[str, QuoteResponse | None])
def get_run_quotes(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, QuoteResponse | None]:
    """Batch-fetch live Finnhub /quote for every ticker in this run's watchlist.

    Returns a dict keyed by ticker; value is ``None`` for tickers whose quote
    fetch failed (unknown symbol, 429-exhausted, etc.) — frontend renders
    these as em-dash placeholders. The whole batch is serialized through
    Finnhub's global rate-limit bucket (~57 req/min), so Top-N=20 takes
    roughly 20-25 seconds end-to-end.
    """
    run = ScanRunRepository(db).get_by_id_for_user(run_id, user_id=current_user.id)
    if not run:
        raise HTTPException(404, f"No scan run with id {run_id}")

    entries = WatchlistEntryRepository(db).list_for_run(run_id)
    tickers = [e.ticker for e in entries]
    if not tickers:
        return {}

    client = make_data_client()
    if not hasattr(client, "get_quote"):
        # Configured provider doesn't expose quotes (e.g. FD-only). Frontend
        # treats all-None the same as missing data and shows em-dashes.
        return {t: None for t in tickers}

    out: dict[str, QuoteResponse | None] = {}
    try:
        with ThreadPoolExecutor(max_workers=recommend_max_workers()) as pool:
            futures = {pool.submit(client.get_quote, t): t for t in tickers}
            for fut in as_completed(futures):
                t = futures[fut]
                try:
                    q = fut.result()
                except Exception as e:
                    logger.warning("get_quote failed for %s: %s", t, e)
                    out[t] = None
                    continue
                if q is None:
                    out[t] = None
                else:
                    out[t] = QuoteResponse(
                        ticker=q.ticker,
                        current_price=q.current_price,
                        prev_close=q.prev_close,
                        percent_change=q.percent_change,
                        asof_timestamp=q.asof_timestamp,
                    )
    finally:
        closer = getattr(client, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                pass
    return out


@router.get("/runs/{run_id}/stream")
async def stream_run(
    run_id: int,
    request: Request,
    broadcaster: ScanBroadcaster = Depends(get_broadcaster),
) -> StreamingResponse:
    """SSE stream of ``ScanBroadcaster`` events for ``run_id``.

    Stream stays open until the scan completes (``event: complete`` / ``error``)
    or the client disconnects. If the run has already finished by the time the
    client subscribes, the stream ends quickly with no events.
    """

    async def event_generator():
        # Send a heartbeat-style start event so the client gets a response immediately.
        yield _sse_event("start", {"run_id": run_id})

        gen = broadcaster.subscribe(run_id)
        try:
            async for ev in gen:
                if await request.is_disconnected():
                    break
                event_name = ev.get("event", "progress")
                yield _sse_event(event_name, ev)
        finally:
            # Async generators clean themselves up when closed; nothing else to do.
            pass

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _validate_cron(expr: str) -> None:
    try:
        CronTrigger.from_crontab(expr, timezone="America/New_York")
    except (ValueError, TypeError) as e:
        raise HTTPException(400, f"Invalid cron expression {expr!r}: {e}")


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
