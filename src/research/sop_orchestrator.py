"""Top-level SOP orchestrator for Phase 4 Analyze runs.

run_sop dispatches all sections in SECTION_ORDER. User-excluded sections
emit 'n/a -- user excluded' payloads. Missing implementations emit
'no runner registered' (Phase 4 rollout is incremental, but Tasks 5-13
ship all 16 sections so this only fires if a registry import broke).

Router (Phase 2) runs first when use_personas=True; its assignments
are stashed under prior['_persona_assignments'] so DebateSection can
read them.

Technical-signal backtest (Task 14) runs once and is appended as a
'Backtest Validation' sub-section to Technical's markdown.
"""

from __future__ import annotations

import logging
from datetime import date

from src.research.backtest_signal import run_signal_backtest
from src.research.charts.render import render_equity_curve_b64
from src.research.models import (
    AnalyzeReport,
    AnalyzeRequest,
    BacktestVerdict,
    SECTION_ORDER,
    SectionPayload,
)
from src.research.router import route_personas
from src.research.sections import SECTION_REGISTRY
from src.research.sections.base import SectionContext
from src.research.shared_data import fetch_shared_data

logger = logging.getLogger(__name__)


def _persona_for(assignments: dict | None, section_name: str) -> str | None:
    if not assignments:
        return None
    value = assignments.get(section_name)
    return value if isinstance(value, str) else None


def _backtest_validation_md(b: BacktestVerdict) -> str:
    md = (
        "\n\n### Backtest Validation\n\n"
        f"Signal tested: **{b.signal}**  \n"
        f"Window: {b.window_start} -> {b.window_end}  \n"
        f"Occurrences: {b.n_signals}  \n"
    )
    if b.win_rate_20d is not None and b.avg_return_20d is not None and b.t_stat is not None:
        md += (
            f"Win rate (20d): {b.win_rate_20d * 100:.0f}%  \n"
            f"Avg return (20d): {b.avg_return_20d * 100:+.2f}%  \n"
            f"t-statistic: {b.t_stat:.2f}  \n"
        )
    md += f"\n**Verdict:** {b.verdict}\n"
    return md


def run_sop(request: AnalyzeRequest) -> AnalyzeReport:
    """End-to-end SOP runner. Returns AnalyzeReport with all sections,
    persona assignments (when use_personas), backtest verdict, and
    rendered_html=None (Task 16's render_sop populates that)."""
    scan_date = date.today().isoformat()
    shared = fetch_shared_data(request.ticker, scan_date)

    # Router: only when persona-mode is on
    persona_assignments: dict | None = None
    if request.use_personas:
        try:
            # route_personas was built for ResearchRequest in Phase 2; adapt
            from src.research.models import ResearchRequest
            adapter = ResearchRequest(
                ticker=request.ticker,
                holding_status="watching",
                target_position_pct=0.05,
                risk_tolerance=request.risk_tolerance,
                report_goal="general_research",
                use_personas=True,
                scanner_context=None,
            )
            persona_assignments = route_personas(adapter, shared)
        except Exception as e:
            logger.exception("router failed: %s", e)
            persona_assignments = None

    # Technical-signal backtest runs once; attached to Technical section
    backtest: BacktestVerdict | None = None
    try:
        backtest = run_signal_backtest(shared, signal="auto")
    except Exception as e:
        logger.exception("backtest failed: %s", e)
        backtest = None

    # Stash persona assignments under a magic key so DebateSection sees them
    sections: dict[str, SectionPayload] = {}
    if persona_assignments is not None:
        sections["_persona_assignments"] = SectionPayload(
            name="_persona_assignments",
            markdown="",
            structured=persona_assignments,
            skipped=False,
            persona_used=None,
        )

    # Iterate SECTION_ORDER (only the canonical names — the magic key
    # stays in sections dict but is not dispatched)
    for name in SECTION_ORDER:
        if name not in request.included_sections:
            sections[name] = SectionPayload(
                name=name,
                markdown=f"## {name}\n\n_n/a -- user excluded_\n",
                structured=None,
                skipped=True,
                persona_used=None,
                skip_reason="user excluded this section",
            )
            continue
        runner = SECTION_REGISTRY.get(name)
        if runner is None:
            sections[name] = SectionPayload(
                name=name,
                markdown=f"## {name}\n\n_section not yet implemented_\n",
                structured=None,
                skipped=True,
                persona_used=None,
                skip_reason="no runner registered",
            )
            continue
        ctx = SectionContext(
            request=request,
            shared=shared,
            persona=_persona_for(persona_assignments, name),
            prior=dict(sections),  # snapshot — section sees everything before it
        )
        try:
            payload = runner.run(ctx)
        except Exception as e:
            logger.exception("section %s raised: %s", name, e)
            payload = SectionPayload(
                name=name,
                markdown=f"## {name}\n\n_unavailable: {e}_\n",
                structured=None,
                skipped=True,
                persona_used=None,
                skip_reason=f"unhandled exception: {e}",
            )
        sections[name] = payload

    # Append Backtest Validation to Technical's markdown + embed equity-curve PNG
    if (
        backtest is not None
        and "technical" in sections
        and not sections["technical"].skipped
    ):
        tech = sections["technical"]

        # Generate inline equity-curve b64 for email/web consumption.
        # Pulled from shared.prices closes + backtest.signal_indices (which
        # the Phase 5A backtest now exposes). On any failure (e.g. matplotlib
        # not installed, empty prices), structured stays None and the
        # rendered HTML simply omits the inline image — the K-line endpoint
        # will still serve PNGs on demand.
        chart_b64: str | None = None
        try:
            from src.research.backtest_signal import _closes
            closes = _closes(shared)
            idx = backtest.signal_indices or []
            chart_b64 = render_equity_curve_b64(closes, idx, horizon=20)
        except Exception as e:
            logger.exception("equity-curve chart render failed: %s", e)

        new_structured: dict | None
        if isinstance(tech.structured, dict):
            new_structured = dict(tech.structured)
        elif tech.structured is None:
            new_structured = {} if chart_b64 else None
        else:
            new_structured = tech.structured  # keep non-dict structured as-is
        if chart_b64 and isinstance(new_structured, dict):
            new_structured["chart_equity_curve_b64"] = chart_b64

        sections["technical"] = SectionPayload(
            name="technical",
            markdown=tech.markdown + _backtest_validation_md(backtest),
            structured=new_structured,
            skipped=False,
            persona_used=tech.persona_used,
        )

    return AnalyzeReport(
        request=request,
        sections=sections,
        persona_assignments=persona_assignments,
        backtest=backtest,
        rendered_html=None,
    )
