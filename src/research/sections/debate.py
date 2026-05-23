"""Debate - wraps Phase 2's run_debate. Only runs when use_personas
AND router picked 2 debate personas. Otherwise emits skipped payload.

The persona assignments are stored in ctx.prior under the magic key
'_persona_assignments' by the orchestrator (Task 15)."""

from __future__ import annotations

import logging

from src.research.models import SectionPayload
from src.research.modules.debate import run_debate
from src.research.sections import SECTION_REGISTRY
from src.research.sections.base import Section, SectionContext

logger = logging.getLogger(__name__)


class DebateSection(Section):
    name = "debate"
    supports_personas = []

    def run(self, ctx: SectionContext) -> SectionPayload:
        if not ctx.request.use_personas:
            return SectionPayload(
                name=self.name,
                markdown="## Debate Summary\n\n_n/a - personas disabled_\n",
                structured=None, skipped=True, persona_used=None,
                skip_reason="use_personas=False",
            )

        # Magic key: orchestrator stows persona_assignments here
        assignments_payload = ctx.prior.get("_persona_assignments")
        debate_personas = []
        if assignments_payload and isinstance(assignments_payload.structured, dict):
            d = assignments_payload.structured.get("debate")
            if isinstance(d, list):
                debate_personas = d

        if len(debate_personas) != 2:
            return SectionPayload(
                name=self.name,
                markdown="## Debate Summary\n\n_n/a - router did not pick 2 debate personas_\n",
                structured=None, skipped=True, persona_used=None,
                skip_reason=f"debate needs exactly 2 personas, got {debate_personas}",
            )

        # Phase 2's run_debate takes ResearchRequest, not AnalyzeRequest -
        # build a minimal adapter.
        from src.research.models import ResearchRequest
        adapter = ResearchRequest(
            ticker=ctx.request.ticker, holding_status="watching",
            target_position_pct=0.05, risk_tolerance=ctx.request.risk_tolerance,
            report_goal="general_research", use_personas=True,
            scanner_context=None,
        )
        try:
            module_result = run_debate(adapter, ctx.shared, debate_personas)
        except Exception as e:
            logger.exception("debate raised: %s", e)
            return SectionPayload(
                name=self.name,
                markdown="## Debate Summary\n\n_unavailable_\n",
                structured=None, skipped=True, persona_used=None,
                skip_reason=str(e),
            )

        return SectionPayload(
            name=self.name,
            markdown="## Debate Summary\n\n" + module_result.markdown,
            structured={"debate_personas": debate_personas,
                        "transcript_markdown": module_result.markdown},
            skipped=module_result.skipped,
            persona_used=module_result.persona_used,
            skip_reason=module_result.skip_reason if module_result.skipped else None,
        )


SECTION_REGISTRY["debate"] = DebateSection()
