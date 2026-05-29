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
from datetime import date as _date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.backend.database import get_db
from app.backend.models.research_schemas import (
    AnalyzeReportDetail,
    AnalyzeRunRequest,
    BacktestSummaryPayload,
    BacktestVerdictAPI,
    ResearchReportDetail,
    ResearchReportSummary,
    ResearchRunRequest,
    SectionPayloadAPI,
    TradePlanPayload,
    VerdictPayload,
)
from app.backend.repositories.research_repository import ResearchReportRepository
from src.research.backtest_signal import _closes, run_signal_backtest
from src.research.charts.render import render_equity_curve_png, render_kline_png
from src.research.html_render import render_html, render_sop
from src.research.models import AnalyzeRequest, ResearchRequest, SECTION_ORDER
from src.research.persist import state_to_db_kwargs
from src.research.pipeline import run_research
from src.research.shared_data import fetch_shared_data
from src.research.sop_orchestrator import run_sop

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


@router.delete("/reports/{report_id}", status_code=204)
def delete_report(report_id: int, db: Session = Depends(get_db)) -> Response:
    """Delete a saved report (used by the sidebar Recent Reports list)."""
    if not ResearchReportRepository(db).delete(report_id):
        raise HTTPException(404, f"No research report with id {report_id}")
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Phase 4 — POST /research/analyze (SOP pipeline)
# ---------------------------------------------------------------------------


def _to_analyze_request(req: AnalyzeRunRequest) -> AnalyzeRequest:
    """Convert the API schema to the internal dataclass."""
    return AnalyzeRequest(
        ticker=req.ticker,
        objective=req.objective,
        position_budget_usd=req.position_budget_usd,
        already_holds=req.already_holds,
        cost_basis_usd=req.cost_basis_usd,
        risk_tolerance=req.risk_tolerance,
        use_personas=req.use_personas,
        included_sections=(
            set(req.included_sections) if req.included_sections
            else set(SECTION_ORDER)
        ),
        persona_overrides=req.persona_overrides,
        debate_rounds=req.debate_rounds,
        report_language=req.report_language,
        market=req.market,
    )


def _report_to_detail(row, *, report_dict) -> AnalyzeReportDetail:
    """Compose AnalyzeReportDetail from a DB row + the in-memory
    AnalyzeReport dict. report_dict is the live result from run_sop
    (with SectionPayload objects), not the DB JSON."""
    arq = row.analyze_request_json or {}
    sections_api: dict[str, SectionPayloadAPI] = {}
    for name, payload in (report_dict.get("sections") or {}).items():
        if name.startswith("_"):
            continue  # skip magic keys like _persona_assignments
        sections_api[name] = SectionPayloadAPI(
            name=payload.name,
            markdown=payload.markdown,
            structured=payload.structured if isinstance(payload.structured, (dict, list)) else None,
            skipped=payload.skipped,
            persona_used=payload.persona_used,
            skip_reason=payload.skip_reason,
        )
    bt = report_dict.get("backtest")
    backtest_api = BacktestVerdictAPI(
        signal=bt.signal, window_start=bt.window_start, window_end=bt.window_end,
        n_signals=bt.n_signals, win_rate_20d=bt.win_rate_20d,
        avg_return_20d=bt.avg_return_20d, t_stat=bt.t_stat,
        significant=bt.significant, verdict=bt.verdict,
    ) if bt is not None else None

    # Lift the verdict (buy/sell/hold + confidence) out of the
    # executive_summary section so the frontend can show a top-of-report card.
    verdict_api: VerdictPayload | None = None
    exec_p = (report_dict.get("sections") or {}).get("executive_summary")
    exec_struct = getattr(exec_p, "structured", None)
    if isinstance(exec_struct, dict):
        rec = exec_struct.get("recommendation")
        conf = exec_struct.get("confidence_score")
        if rec in ("strong_buy", "buy", "hold", "sell", "strong_sell") and isinstance(
            conf, (int, float)
        ):
            verdict_api = VerdictPayload(
                recommendation=rec,
                confidence_score=int(conf),
                one_liner=exec_struct.get("overall_view") or "",
            )

    return AnalyzeReportDetail(
        id=row.id,
        ticker=row.ticker,
        scan_date=row.scan_date,
        created_at=row.created_at,
        duration_seconds=row.duration_seconds,
        objective=arq.get("objective", "general_research"),
        position_budget_usd=arq.get("position_budget_usd"),
        already_holds=arq.get("already_holds", False),
        cost_basis_usd=arq.get("cost_basis_usd"),
        risk_tolerance=arq.get("risk_tolerance", "balanced"),
        use_personas=arq.get("use_personas", False),
        persona_assignments=report_dict.get("persona_assignments"),
        sections=sections_api,
        backtest=backtest_api,
        verdict=verdict_api,
    )


@router.post("/analyze", response_model=AnalyzeReportDetail)
def trigger_analyze(
    req: AnalyzeRunRequest,
    db: Session = Depends(get_db),
) -> AnalyzeReportDetail:
    """Run the SOP pipeline, persist, return AnalyzeReportDetail.

    SYNCHRONOUS — full SOP takes 60-120s (~14 LLM calls). Long-poll /
    streaming is deferred.
    """
    internal_req = _to_analyze_request(req)
    t0 = time.monotonic()
    try:
        report = run_sop(internal_req)
    except Exception as e:
        logger.exception("analyze run failed for %s", req.ticker)
        raise HTTPException(500, f"analyze pipeline failed: {type(e).__name__}: {e}")
    duration = time.monotonic() - t0

    # Render once without report_id to get the persisted HTML; we re-render
    # below with the freshly-inserted id so K-line <img> tags point at the
    # right URL.
    html = render_sop(report)
    report["rendered_html"] = html

    arq_dict = {
        "ticker": internal_req.ticker,
        "objective": internal_req.objective,
        "position_budget_usd": internal_req.position_budget_usd,
        "already_holds": internal_req.already_holds,
        "cost_basis_usd": internal_req.cost_basis_usd,
        "risk_tolerance": internal_req.risk_tolerance,
        "use_personas": internal_req.use_personas,
        "included_sections": sorted(internal_req.included_sections),
    }
    sections_json = {
        name: {
            "markdown": p.markdown, "structured": p.structured,
            "skipped": p.skipped, "persona_used": p.persona_used,
            "skip_reason": p.skip_reason,
        }
        for name, p in (report.get("sections") or {}).items()
        if not name.startswith("_")
    }
    today_iso = _date.today().isoformat()
    report_kwargs = {
        "ticker": internal_req.ticker,
        "scan_date": today_iso,
        "request_json": arq_dict,
        "report_markdown": "\n\n".join(
            p.markdown for name, p in (report.get("sections") or {}).items()
            if not name.startswith("_")
        ),
        "rendered_html": html,
        "use_personas": internal_req.use_personas,
        "persona_assignments_json": report.get("persona_assignments"),
        "duration_seconds": duration,
        "analyze_request_json": arq_dict,
        "sections_json": sections_json,
    }
    repo = ResearchReportRepository(db)
    row = repo.create_analyze(report=report_kwargs)

    # Re-render with the freshly-allocated report id so the K-line chart
    # <img> tag can point at /research/reports/{id}/chart/kline-daily.png.
    # Update the persisted row in place.
    try:
        html_with_id = render_sop(report, report_id=row.id)
        row.rendered_html = html_with_id
        db.commit()
        db.refresh(row)
        report["rendered_html"] = html_with_id
    except Exception as e:
        logger.exception("re-render with report_id failed (keeping initial HTML): %s", e)

    return _report_to_detail(row, report_dict=report)


# ---------------------------------------------------------------------------
# Phase 5A — chart PNG endpoint
# ---------------------------------------------------------------------------

_CHART_TYPES = {"kline-daily", "kline-weekly", "equity-curve"}


@router.get(
    "/reports/{report_id}/chart/{chart_type}.png",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
def get_report_chart(
    report_id: int,
    chart_type: str,
    db: Session = Depends(get_db),
):
    """Regenerate a chart PNG on demand for the given report.

    No cache (v1): each request re-fetches shared data and re-renders.
    Cheap enough (~200ms) for the dev environment; revisit with ETag /
    file cache once we have multiple concurrent users.
    """
    if chart_type not in _CHART_TYPES:
        raise HTTPException(404, f"unknown chart type: {chart_type}")

    report = ResearchReportRepository(db).get_by_id(report_id)
    if not report:
        raise HTTPException(404, f"No research report with id {report_id}")

    try:
        shared = fetch_shared_data(report.ticker, report.scan_date)
    except Exception as e:
        logger.exception("fetch_shared_data failed for chart endpoint: %s", e)
        raise HTTPException(500, f"failed to load shared data: {type(e).__name__}")

    closes = _closes(shared)

    if chart_type == "kline-daily":
        png = render_kline_png(closes, kind="daily")
    elif chart_type == "kline-weekly":
        png = render_kline_png(closes, kind="weekly")
    else:  # equity-curve
        verdict = run_signal_backtest(shared, signal="auto")
        idx = verdict.signal_indices or []
        png = render_equity_curve_png(closes, idx, horizon=20)

    return Response(content=png, media_type="image/png")
