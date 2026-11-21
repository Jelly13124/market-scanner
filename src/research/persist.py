"""ResearchState -> ResearchReport+ResearchTradePlan DB row kwargs.

The repository in app.backend.repositories.research_repository expects
two flat dicts (one for the report row, one for the plan row). This
helper does the conversion so the route handler stays thin.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

from src.research.models import ResearchState


def state_to_db_kwargs(
    state: ResearchState,
    *,
    duration_seconds: float,
) -> tuple[dict, dict]:
    """Return (report_kwargs, plan_kwargs) for ResearchReportRepository
    .create_with_plan."""
    request = state["request"]
    plan = state["strategy"]
    backtest = state["backtest_summary"]

    ctx = request.scanner_context or {}
    scan_date = ctx.get("scan_date") or date.today().isoformat()

    report_kwargs = {
        "ticker": request.ticker,
        "scan_date": scan_date,
        "request_json": asdict(request),
        "report_markdown": state.get("report_markdown") or "",
        "rendered_html": state.get("rendered_html") or "",
        "use_personas": bool(request.use_personas),
        "persona_assignments_json": state.get("persona_assignments"),
        "duration_seconds": duration_seconds,
    }

    plan_kwargs = {
        "report_id": 0,  # placeholder; repo overwrites with FK
        "direction": plan.direction,
        "entry_price": plan.entry_price,
        "target_price": plan.target_price,
        "stop_price": plan.stop_price,
        "horizon_days": plan.horizon_days,
        "sizing_pct": plan.sizing_pct,
        "confidence": plan.confidence,
        "rationale": plan.rationale,
        "backtest_matches_found": backtest.matches_found,
        "backtest_win_rate": backtest.win_rate,
        "backtest_avg_pnl_pct": backtest.avg_pnl_pct,
        "backtest_max_drawdown_pct": backtest.max_drawdown_pct,
        "backtest_avg_holding_days": backtest.avg_holding_days,
        "backtest_sample_quality": backtest.sample_quality,
        "backtest_caveat": backtest.caveat,
    }
    return report_kwargs, plan_kwargs


def analyze_to_db_kwargs(request, report, *, duration_seconds):
    """Persist the same request, origin and market observations for manual and auto-SOP runs."""
    from src.research.scan_provenance import analyze_markdown
    from src.storage.mongo import json_value

    source_id = request.source_scan_evidence["scan_result_id"] if request.source_scan_evidence else None
    inputs = json_value(request)
    inputs.update(
        source_scan_result_id=source_id or (request.source_scan_evidence or {}).get("mongo_scan_result_id"),
        analysis_market_evidence=report.get("analysis_market_evidence"),
        storage_status=report.get("storage_status"),
        mongo_report_id=report.get("mongo_report_id"),
        analysis_run_id=report.get("analysis_run_id"),
        analysis_status=report.get("analysis_status"),
        usage=report.get("usage", {}),
    )
    sections = {
        name: {"markdown": p.markdown, "structured": p.structured, "skipped": p.skipped,
               "persona_used": p.persona_used, "skip_reason": p.skip_reason}
        for name, p in report["sections"].items() if not name.startswith("_")
    }
    return {
        "ticker": request.ticker,
        "scan_date": date.today().isoformat(),
        "source_scan_result_id": source_id,
        "request_json": inputs,
        "analyze_request_json": inputs,
        "report_markdown": analyze_markdown(report),
        "sections_json": sections,
        "rendered_html": report["rendered_html"],
        "use_personas": request.use_personas,
        "persona_assignments_json": report.get("persona_assignments"),
        "duration_seconds": duration_seconds,
    }
