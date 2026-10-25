"""Scanner→Agent pipeline REST API.

Endpoints:

    POST   /pipeline/run            retired (410)
    GET    /pipeline/runs           list recent runs (paginated)
    GET    /pipeline/runs/{run_id}  full detail (watchlist + signals + decisions)
    GET    /pipeline/templates      analyst rosters + agent metadata
    GET    /pipeline/schedule       caller's daily-cron config (created on first GET)
    PATCH  /pipeline/schedule       update the caller's config

POST /pipeline/run is retired (410). Existing runs remain readable.

Wave 4 (Task 4.3): every endpoint requires a Bearer token. Runs are stamped
with + scoped to the caller's ``user_id`` (cross-tenant get → 404). The
``pipeline_schedule`` row is now per-user (it was a global id=1 singleton);
GET/PATCH operate on the caller's own row, created lazily on first access.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.backend.auth.dependencies import get_current_user
from app.backend.database import get_db
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
)

router = APIRouter(prefix="/pipeline")


@router.post("/run", response_model=RunPipelineResponse, status_code=410)
def trigger_run(
    req: RunPipelineRequest,
    current_user: User = Depends(get_current_user),
) -> RunPipelineResponse:
    """Retired entry point; do not create a run or schedule background work."""
    raise HTTPException(410, "Legacy LangGraph Analyze was removed; use /research/analyze.")


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
    if patch.enabled is True:
        raise HTTPException(410, "Legacy LangGraph Analyze scheduling was removed; use Analyze report schedules.")
    # Validate template name if changing.
    if patch.template is not None and patch.template not in TEMPLATES:
        raise HTTPException(
            400,
            f"unknown template {patch.template!r}; valid: {sorted(TEMPLATES)}",
        )
    updated = PipelineScheduleRepository(db).update_for_user(current_user.id, **patch.model_dump(exclude_unset=True))
    return PipelineScheduleResponse.model_validate(updated)
