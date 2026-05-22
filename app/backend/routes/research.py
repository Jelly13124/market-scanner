"""REST API for the per-stock research pipeline.

Endpoints:
    POST   /research/run                  run pipeline + persist + return detail (sync)
    GET    /research/reports              list reports newest-first
    GET    /research/reports/{id}         full detail JSON
    GET    /research/reports/{id}/html    rendered HTML payload

POST /research/run is SYNCHRONOUS (not BackgroundTasks like /pipeline/run).
A research run is short - 30-90s including 9-12 LLM calls - and the caller
typically wants the report back inline. Long-poll / streaming is deferred.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.backend.database import get_db
from app.backend.models.research_schemas import (
    BacktestSummaryPayload,
    ResearchReportDetail,
    ResearchReportSummary,
    ResearchRunRequest,
    TradePlanPayload,
)
from app.backend.repositories.research_repository import ResearchReportRepository
from src.research.html_render import render_html
from src.research.models import ResearchRequest
from src.research.persist import state_to_db_kwargs
from src.research.pipeline import run_research

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/research")


def _api_request_to_internal(req: ResearchRunRequest) -> ResearchRequest:
    """ResearchRunRequest (API) -> ResearchRequest (internal dataclass)."""
    return ResearchRequest(
        ticker=req.ticker,
        holding_status=req.holding_status,
        target_position_pct=req.target_position_pct,
        risk_tolerance=req.risk_tolerance,
        report_goal=req.report_goal,
        use_personas=req.use_personas,
        scanner_context=None,
    )


def _detail_from_row_and_plan(report, plan) -> ResearchReportDetail:
    """Compose ResearchReportDetail from the two ORM rows."""
    return ResearchReportDetail(
        id=report.id,
        ticker=report.ticker,
        scan_date=report.scan_date,
        created_at=report.created_at,
        use_personas=bool(report.use_personas),
        persona_assignments=report.persona_assignments_json,
        report_markdown=report.report_markdown,
        duration_seconds=report.duration_seconds,
        plan=TradePlanPayload(
            direction=plan.direction,
            entry_price=plan.entry_price,
            target_price=plan.target_price,
            stop_price=plan.stop_price,
            horizon_days=plan.horizon_days,
            sizing_pct=plan.sizing_pct,
            confidence=plan.confidence,
            rationale=plan.rationale,
        ),
        backtest=BacktestSummaryPayload(
            matches_found=plan.backtest_matches_found,
            win_rate=plan.backtest_win_rate,
            avg_pnl_pct=plan.backtest_avg_pnl_pct,
            max_drawdown_pct=plan.backtest_max_drawdown_pct,
            avg_holding_days=plan.backtest_avg_holding_days,
            sample_quality=plan.backtest_sample_quality,
            caveat=plan.backtest_caveat,
        ),
    )


@router.post("/run", response_model=ResearchReportDetail)
def trigger_run(
    req: ResearchRunRequest,
    db: Session = Depends(get_db),
) -> ResearchReportDetail:
    """Run the research pipeline, persist the report + plan, return detail."""
    internal_req = _api_request_to_internal(req)
    t0 = time.monotonic()
    try:
        state = run_research(internal_req)
    except Exception as e:
        logger.exception("research run failed for %s", req.ticker)
        raise HTTPException(500, f"research pipeline failed: {type(e).__name__}: {e}")
    duration = time.monotonic() - t0

    # Render HTML AFTER pipeline so module_results are populated
    html = render_html(state)
    state["rendered_html"] = html

    report_kwargs, plan_kwargs = state_to_db_kwargs(state, duration_seconds=duration)
    repo = ResearchReportRepository(db)
    report_row = repo.create_with_plan(report=report_kwargs, plan=plan_kwargs)
    plan_row = repo.get_plan_for_report(report_row.id)
    return _detail_from_row_and_plan(report_row, plan_row)


@router.get("/reports", response_model=list[ResearchReportSummary])
def list_reports(
    ticker: str | None = None,
    scan_date: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> list[ResearchReportSummary]:
    if limit < 1 or limit > 200:
        raise HTTPException(400, "limit must be between 1 and 200")
    rows = ResearchReportRepository(db).list_reports(
        ticker=ticker.upper() if ticker else None,
        scan_date=scan_date,
        limit=limit,
    )
    return [ResearchReportSummary.model_validate(r) for r in rows]


@router.get("/reports/{report_id}", response_model=ResearchReportDetail)
def get_report(report_id: int, db: Session = Depends(get_db)) -> ResearchReportDetail:
    repo = ResearchReportRepository(db)
    report = repo.get_by_id(report_id)
    if not report:
        raise HTTPException(404, f"No research report with id {report_id}")
    plan = repo.get_plan_for_report(report_id)
    if not plan:
        raise HTTPException(500, f"Report {report_id} has no paired plan row")
    return _detail_from_row_and_plan(report, plan)


@router.get("/reports/{report_id}/html", response_class=HTMLResponse)
def get_report_html(report_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    report = ResearchReportRepository(db).get_by_id(report_id)
    if not report:
        raise HTTPException(404, f"No research report with id {report_id}")
    return HTMLResponse(content=report.rendered_html or "<html></html>")
