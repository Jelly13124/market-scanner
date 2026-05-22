"""Debate module — simulate a 2-round transcript between two router-picked
investor personas.

NOT an AnalysisModule subclass — the signature differs (consumes a list
of persona names, not a single persona). Pipeline calls run_debate()
directly when router.persona_assignments['debate'] has exactly 2 entries.

Phase 2 v1: single LLM call that simulates the full debate. Cheaper
than dispatching one call per persona per round. Phase 3 or later may
expand to true multi-agent dispatch if outputs disappoint.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from src.research.llm import call_research_llm
from src.research.models import ModuleResult, ResearchRequest
from src.research.personas import PERSONA_REGISTRY
from src.research.shared_data import SharedData

logger = logging.getLogger(__name__)


class _DebateTranscript(BaseModel):
    transcript: str = Field(
        description=(
            "Two-round debate transcript. Each round contains one statement "
            "from each persona. Use markdown bold for speaker labels: "
            "`**Buffett (Round 1):**`"
        )
    )
    verdict: str = Field(
        description="1-2 sentences identifying which persona made the stronger case."
    )


def run_debate(
    request: ResearchRequest,
    shared_data: SharedData,
    personas: list[str],
) -> ModuleResult:
    """Run a two-persona debate. ``personas`` must be a list of exactly
    two persona names present in PERSONA_REGISTRY. Otherwise returns a
    skipped ModuleResult."""
    if len(personas) != 2 or not all(p in PERSONA_REGISTRY for p in personas):
        return ModuleResult(
            module_name="debate", persona_used=None, markdown="",
            skipped=True,
            skip_reason=f"debate needs exactly 2 valid personas, got {personas}",
        )

    p1 = PERSONA_REGISTRY[personas[0]]
    p2 = PERSONA_REGISTRY[personas[1]]

    sector = (shared_data.company_facts or {}).get("sector", "Unknown")

    prompt = (
        f"You are simulating a two-round investment debate between two "
        f"famous investors about ticker {request.ticker} ({sector} sector).\n\n"
        f"=== Persona A: {p1.name.title()} ===\n"
        f"{p1.system_addition()}\n\n"
        f"=== Persona B: {p2.name.title()} ===\n"
        f"{p2.system_addition()}\n\n"
        f"Run the debate as follows:\n"
        f"  Round 1: {p1.name.title()} states their thesis on {request.ticker} "
        f"(2-4 sentences).\n"
        f"  Round 1: {p2.name.title()} states their thesis (2-4 sentences).\n"
        f"  Round 2: {p1.name.title()} responds to the strongest point {p2.name.title()} "
        f"made, sharpening or conceding (2-3 sentences).\n"
        f"  Round 2: {p2.name.title()} does the same against {p1.name.title()}'s thesis (2-3 sentences).\n\n"
        f"Format each statement with a markdown bold label like "
        f"`**{p1.name.title()} (Round 1):**` followed by the prose.\n\n"
        f"Finally produce a 1-2 sentence VERDICT identifying which persona made the "
        f"stronger case on this ticker AT THIS MOMENT — given the sector and "
        f"the ticker's profile. Do not split the difference; pick one."
    )

    out = call_research_llm(
        prompt, _DebateTranscript,
        default_factory=lambda: _DebateTranscript(
            transcript=(
                f"**{p1.name.title()}:** debate LLM failed.\n\n"
                f"**{p2.name.title()}:** debate LLM failed."
            ),
            verdict="Debate generation failed; no verdict.",
        ),
    )

    markdown = out.transcript + "\n\n**Verdict:** " + out.verdict
    return ModuleResult(
        module_name="debate",
        persona_used=f"{personas[0]}+{personas[1]}",
        markdown=markdown,
        key_metrics={},
    )
