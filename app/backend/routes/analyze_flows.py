"""REST API for saved AnalyzeFlow templates (Phase 5D).

CRUD over /analyze-flows. Each flow is a named template the UI loads
back into the Analyze panel's React Flow canvas. The canvas itself is
visual scaffolding — what we persist is the orchestrator-shaped config
(included sections + persona overrides).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.backend.database import get_db
from app.backend.models.analyze_flow_schemas import (
    AnalyzeFlowCreate,
    AnalyzeFlowResponse,
    AnalyzeFlowUpdate,
)
from app.backend.repositories.analyze_flow_repository import AnalyzeFlowRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analyze-flows")


@router.get("", response_model=list[AnalyzeFlowResponse])
def list_flows(
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[AnalyzeFlowResponse]:
    if limit < 1 or limit > 500:
        raise HTTPException(400, "limit must be between 1 and 500")
    rows = AnalyzeFlowRepository(db).list(limit=limit)
    return [AnalyzeFlowResponse.model_validate(r) for r in rows]


@router.post("", response_model=AnalyzeFlowResponse, status_code=201)
def create_flow(
    req: AnalyzeFlowCreate,
    db: Session = Depends(get_db),
) -> AnalyzeFlowResponse:
    repo = AnalyzeFlowRepository(db)
    if repo.get_by_name(req.name) is not None:
        raise HTTPException(409, f"AnalyzeFlow with name '{req.name}' already exists")
    row = repo.create(
        name=req.name,
        included_sections=req.included_sections,
        use_personas=req.use_personas,
        persona_overrides=req.persona_overrides,
    )
    return AnalyzeFlowResponse.model_validate(row)


@router.get("/{flow_id}", response_model=AnalyzeFlowResponse)
def get_flow(flow_id: int, db: Session = Depends(get_db)) -> AnalyzeFlowResponse:
    row = AnalyzeFlowRepository(db).get(flow_id)
    if row is None:
        raise HTTPException(404, f"No AnalyzeFlow with id {flow_id}")
    return AnalyzeFlowResponse.model_validate(row)


@router.patch("/{flow_id}", response_model=AnalyzeFlowResponse)
def update_flow(
    flow_id: int,
    req: AnalyzeFlowUpdate,
    db: Session = Depends(get_db),
) -> AnalyzeFlowResponse:
    repo = AnalyzeFlowRepository(db)
    existing = repo.get(flow_id)
    if existing is None:
        raise HTTPException(404, f"No AnalyzeFlow with id {flow_id}")
    # Guard against renaming into an existing name
    if req.name is not None and req.name != existing.name:
        collision = repo.get_by_name(req.name)
        if collision is not None and collision.id != flow_id:
            raise HTTPException(409, f"AnalyzeFlow with name '{req.name}' already exists")
    row = repo.update(
        flow_id,
        name=req.name,
        included_sections=req.included_sections,
        use_personas=req.use_personas,
        persona_overrides=req.persona_overrides,
    )
    return AnalyzeFlowResponse.model_validate(row)


@router.delete("/{flow_id}", status_code=204, response_class=Response)
def delete_flow(flow_id: int, db: Session = Depends(get_db)) -> Response:
    ok = AnalyzeFlowRepository(db).delete(flow_id)
    if not ok:
        raise HTTPException(404, f"No AnalyzeFlow with id {flow_id}")
    return Response(status_code=204)
