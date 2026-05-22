"""Pipeline orchestration for the research workflow.

Phase 1: linear orchestration with explicit sequencing — no LangGraph
node DAG yet. (LangGraph wiring lands in Phase 2 when the persona-router
introduces conditional edges and the debate node introduces fan-out.
For Phase 1 the sequence is simple enough that a plain function reads
clearer than a graph.)

Sequence:
  1. fetch_shared_data
  2. Run every module except risk_position
  3. Run risk_position with prior_results = the above
  4. synthesize(request, module_results) -> (report, TradePlan)
  5. replay_trade_plan -> BacktestSummary
  6. Assemble ResearchState
"""

from __future__ import annotations

import inspect
import logging
from datetime import date
from pathlib import Path

from src.research.models import (
    BacktestSummary, ModuleResult, ResearchRequest, ResearchState, TradePlan,
)
from src.research.modules import ALL_MODULES
from src.research.modules.detector_backtest import (
    BacktestInputs, replay_trade_plan,
)
from src.research.router import route_personas
from src.research.modules.debate import run_debate
from src.research.shared_data import fetch_shared_data
from src.research.synthesizer import synthesize

logger = logging.getLogger(__name__)


def _scan_date(request: ResearchRequest) -> str:
    """Today's date for the data fetch. Cron passes scanner_context with
    its own scan_date implicitly; for on-demand calls without scanner
    context we use today."""
    ctx = request.scanner_context or {}
    return ctx.get("scan_date") or date.today().isoformat()


def _history_csv_path(ticker: str) -> Path:
    """Detector trigger history CSV. v1: assume per-ticker file under
    outputs/detector_history/. Missing file -> empty history -> backtest
    returns 'insufficient'."""
    return Path("outputs/detector_history") / f"{ticker}.csv"


def run_research(request: ResearchRequest) -> ResearchState:
    """End-to-end pipeline. Returns a ResearchState with all fields
    populated (or None where appropriate)."""
    scan_date = _scan_date(request)
    shared = fetch_shared_data(request.ticker, scan_date)

    # Router (Phase 2). Only when use_personas; otherwise every module
    # runs objective and debate never fires.
    persona_assignments: dict[str, str | list[str] | None] | None = None
    if request.use_personas:
        try:
            persona_assignments = route_personas(request, shared)
        except Exception as e:
            logger.exception("router failed: %s", e)
            persona_assignments = None

    def _persona_for(module_name: str) -> str | None:
        if not persona_assignments:
            return None
        value = persona_assignments.get(module_name)
        if isinstance(value, str):
            return value
        return None

    module_results: dict[str, ModuleResult] = {}

    risk_position_module = None
    for module_cls in ALL_MODULES:
        if module_cls.__name__ == "RiskPositionModule":
            risk_position_module = module_cls
            continue
        module = module_cls()
        try:
            result = module.run(
                request,
                persona=_persona_for(module.name),
                shared_data=shared,
            )
        except Exception as e:
            logger.exception(
                "module %s raised — should not happen per ABC contract: %s",
                module.name, e,
            )
            result = ModuleResult(
                module_name=module.name, persona_used=None, markdown="",
                skipped=True, skip_reason=f"Unhandled exception: {e}",
            )
        module_results[module.name] = result

    if risk_position_module is not None:
        try:
            m = risk_position_module()
            sig = inspect.signature(m.run)
            kwargs = {}
            if "prior_results" in sig.parameters:
                kwargs["prior_results"] = module_results
            result = m.run(
                request,
                persona=_persona_for("risk_position"),
                shared_data=shared,
                **kwargs,
            )
        except Exception as e:
            logger.exception("risk_position raised: %s", e)
            result = ModuleResult(
                module_name="risk_position", persona_used=None, markdown="",
                skipped=True, skip_reason=f"Unhandled exception: {e}",
            )
        module_results["risk_position"] = result

    # Debate (Phase 2). Only when router picked exactly 2 personas.
    if persona_assignments:
        debate_personas = persona_assignments.get("debate") or []
        if isinstance(debate_personas, list) and len(debate_personas) == 2:
            try:
                debate_result = run_debate(request, shared, debate_personas)
            except Exception as e:
                logger.exception("debate raised: %s", e)
                debate_result = ModuleResult(
                    module_name="debate", persona_used=None, markdown="",
                    skipped=True, skip_reason=f"Unhandled exception: {e}",
                )
            module_results["debate"] = debate_result

    report_md, plan = synthesize(request, module_results)

    triggered: list[str] = []
    if request.scanner_context:
        triggered = list(request.scanner_context.get("triggered_detectors") or [])
    backtest = replay_trade_plan(BacktestInputs(
        ticker=request.ticker,
        triggered_detectors=triggered,
        plan=plan,
        history_csv=_history_csv_path(request.ticker),
    ))

    return ResearchState(
        request=request,
        persona_assignments=persona_assignments,
        module_results=module_results,
        report_markdown=report_md,
        strategy=plan,
        backtest_summary=backtest,
        rendered_html=None,  # Phase 3 populates
    )
