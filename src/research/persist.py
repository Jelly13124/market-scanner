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
