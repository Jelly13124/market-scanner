"""Scanner→Agent pipeline REST API.

Endpoints:

    POST   /pipeline/run            kick off a pipeline run (BackgroundTask)
    GET    /pipeline/runs           list recent runs (paginated)
    GET    /pipeline/runs/{run_id}  full detail (watchlist + signals + decisions)
    GET    /pipeline/templates      analyst rosters + agent metadata
    GET    /pipeline/schedule       caller's daily-cron config (created on first GET)
    PATCH  /pipeline/schedule       update the caller's config

POST /pipeline/run inserts a PENDING row and returns the run_id immediately;
the actual orchestration runs in a FastAPI ``BackgroundTask`` that flips
the row through RUNNING → COMPLETE/ERROR. ``run_pipeline`` is invoked via
``asyncio.to_thread`` because LangGraph + LLM SDK calls block the event
loop otherwise (per implementation plan §Top risks).

Wave 4 (Task 4.3): every endpoint requires a Bearer token. Runs are stamped
with + scoped to the caller's ``user_id`` (cross-tenant get → 404). The
``pipeline_schedule`` row is now per-user (it was a global id=1 singleton);
GET/PATCH operate on the caller's own row, created lazily on first access.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.backend.auth.dependencies import get_current_user
from app.backend.database import SessionLocal, get_db
from app.backend.database.models import User
from app.backend.models.pipeline_schemas import (
    AgentMetadata,
    PipelineRunDetail,
    PipelineRunSummary,
    PipelineScheduleResponse,
    PipelineScheduleUpdateRequest,
    PipelineStatus,
    RunPipelineRequest,
    RunPipelineResponse,
    TemplatesResponse,
)
from app.backend.repositories.pipeline_repository import (
    PipelineRunRepository,
    PipelineScheduleRepository,
)
from src.utils.analysts import get_agents_list
from v2.pipeline import (
    DEFAULT_TEMPLATE,
    TEMPLATES,
    resolve_analysts,
    run_pipeline,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pipeline")


# ---------------------------------------------------------------------------
# Background task implementation
# ---------------------------------------------------------------------------


def _execute_run_in_background(run_id: str, req: RunPipelineRequest) -> None:
    """Background worker that drives one pipeline run from PENDING → done.

    Owns its OWN DB session — we cannot reuse the request-scoped session
    here because it has already been closed by the time this fires.
    """
    db = SessionLocal()
    repo = PipelineRunRepository(db)
    try:
        repo.mark_running(run_id)
        try:
            # run_pipeline is a synchronous, blocking call (scanner pool +
            # LangGraph + multiple LLM round-trips). We're already in a
            # background task — running directly is fine.
            result = run_pipeline(
                scan_date=req.scan_date,
                universe=req.universe,
                universe_tickers=req.universe_tickers,
                top_n=req.top_n,
                template=req.template,
                custom_analysts=req.custom_analysts,
                portfolio=req.portfolio,
                model_name=req.model_name,
                model_provider=req.model_provider,
                persist=False,  # we persist via repo below
            )
        except Exception as e:
            logger.exception("Pipeline run %s failed", run_id)
            repo.mark_error(run_id, f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
            return

        repo.mark_complete(
            run_id,
            watchlist=result.watchlist,
            agent_decisions=result.agent_decisions,
            analyst_signals=result.analyst_signals,
            duration_seconds=result.duration_seconds,
        )
        logger.info("Pipeline run %s completed in %.1fs", run_id, result.duration_seconds)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# POST /pipeline/run
# ---------------------------------------------------------------------------


@router.post("/run", response_model=RunPipelineResponse, status_code=202)
def trigger_run(
    req: RunPipelineRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RunPipelineResponse:
    """Kick off a pipeline run; PENDING row is created synchronously, the
    actual orchestration runs in the background."""
    # Fail fast on bad inputs BEFORE inserting a doomed PENDING row.
    try:
        selected = resolve_analysts(template=req.template, custom=req.custom_analysts)
    except ValueError as e:
        raise HTTPException(400, str(e))

    template_name = req.template if req.template else ("custom" if req.custom_analysts else DEFAULT_TEMPLATE)

    run_id = uuid.uuid4().hex
    PipelineRunRepository(db).create_pending(
        run_id=run_id,
        scan_date=req.scan_date or "(deferred)",  # resolved when worker runs
        template=template_name,
        selected_analysts=selected,
        top_n=req.top_n,
        universe=req.universe,
        user_id=current_user.id,
    )
    background_tasks.add_task(_execute_run_in_background, run_id, req)
    return RunPipelineResponse(run_id=run_id, status=PipelineStatus.PENDING)


# ---------------------------------------------------------------------------
# GET /pipeline/runs[/{run_id}]
# ---------------------------------------------------------------------------


@router.get("/runs", response_model=list[PipelineRunSummary])
def list_runs(
    limit: int = 50,
    template: str | None = None,
    status: PipelineStatus | None = None,
    since: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PipelineRunSummary]:
    """List the caller's recent runs newest-first. Filters AND together; all optional."""
    if limit < 1 or limit > 200:
        raise HTTPException(400, "limit must be between 1 and 200")
    rows = PipelineRunRepository(db).list_runs(
        user_id=current_user.id,
        limit=limit,
        template=template,
        status=status.value if status else None,
        since=since,
    )
    return [PipelineRunSummary.model_validate(r) for r in rows]


@router.get("/runs/{run_id}", response_model=PipelineRunDetail)
def get_run(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PipelineRunDetail:
    row = PipelineRunRepository(db).get_by_id(run_id, user_id=current_user.id)
    if not row:
        raise HTTPException(404, f"No pipeline run with id {run_id}")
    return PipelineRunDetail(
        id=row.id,
        created_at=row.created_at,
        completed_at=row.completed_at,
        scan_date=row.scan_date,
        template=row.template,
        top_n=row.top_n,
        universe=row.universe,
        status=row.status,
        duration_seconds=row.duration_seconds,
        error=row.error,
        selected_analysts=row.selected_analysts or [],
        watchlist=row.watchlist_json,
        agent_decisions=row.agent_decisions_json,
        analyst_signals=row.analyst_signals_json,
    )


# ---------------------------------------------------------------------------
# GET /pipeline/templates
# ---------------------------------------------------------------------------


@router.get("/templates", response_model=TemplatesResponse)
def list_templates() -> TemplatesResponse:
    """Named analyst rosters + the full agent registry, for the UI modal."""
    return TemplatesResponse(
        templates=dict(TEMPLATES),
        default_template=DEFAULT_TEMPLATE,
        agents=[AgentMetadata(**a) for a in get_agents_list()],
    )


# ---------------------------------------------------------------------------
# GET/PATCH /pipeline/schedule
# ---------------------------------------------------------------------------


@router.get("/schedule", response_model=PipelineScheduleResponse)
def get_schedule(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PipelineScheduleResponse:
    # Per-user row, created with defaults (cron OFF) on first access.
    row = PipelineScheduleRepository(db).get_or_create_for_user(current_user.id)
    return PipelineScheduleResponse.model_validate(row)


@router.patch("/schedule", response_model=PipelineScheduleResponse)
def update_schedule(
    patch: PipelineScheduleUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PipelineScheduleResponse:
    # Validate template name if changing.
    if patch.template is not None and patch.template not in TEMPLATES:
        raise HTTPException(
            400,
            f"unknown template {patch.template!r}; valid: {sorted(TEMPLATES)}",
        )
    updated = PipelineScheduleRepository(db).update_for_user(current_user.id, **patch.model_dump(exclude_unset=True))
    return PipelineScheduleResponse.model_validate(updated)
