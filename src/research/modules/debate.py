"""Debate module — simulate an N-round transcript between two router-picked
investor personas.

NOT an AnalysisModule subclass — the signature differs (consumes a list
of persona names, not a single persona). Pipeline calls run_debate()
directly when router.persona_assignments['debate'] has exactly 2 entries.

Phase 2 v1: single LLM call that simulates the full debate. Cheaper
than dispatching one call per persona per round. Phase 3 or later may
expand to true multi-agent dispatch if outputs disappoint.

Phase 5E: rounds is now parameterised (1..5). Default stays 2 here so
Phase 2 callers (src/research/pipeline.py + Phase 2 tests) keep their
original behavior; the Phase 4+ section runner passes the user-chosen
value from AnalyzeRequest.debate_rounds.
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
            "Multi-round debate transcript. Each round contains one statement "
            "from each persona. Use markdown bold for speaker labels: "
            "`**Buffett (Round 1):**`"
        )
    )
    verdict: str = Field(
        description="1-2 sentences identifying which persona made the stronger case."
    )


def _build_round_instructions(p1_name: str, p2_name: str, rounds: int) -> str:
    """Build the per-round prompt instructions.

    Layout by N:
        N=1 → each persona states their thesis once; moderator verdict.
        N=2 → round 1 theses, round 2 challenges (preserves Phase 2 behavior).
        N>=3 → round 1 theses, rounds 2..N-1 back-and-forth challenges,
               round N final positions.
    """
    lines: list[str] = []

    if rounds == 1:
        lines.append(
            f"  Round 1: {p1_name} states their thesis on the ticker (3-5 sentences)."
        )
        lines.append(
            f"  Round 1: {p2_name} states their thesis (3-5 sentences)."
        )
        return "\n".join(lines)

    # Round 1 — opening theses (always)
    lines.append(
        f"  Round 1: {p1_name} states their thesis (2-4 sentences)."
    )
    lines.append(
        f"  Round 1: {p2_name} states their thesis (2-4 sentences)."
    )

    if rounds == 2:
        # Phase 2 behavior — round 2 is direct challenge with verdict to follow.
        lines.append(
            f"  Round 2: {p1_name} responds to the strongest point {p2_name} "
            f"made, sharpening or conceding (2-3 sentences)."
        )
        lines.append(
            f"  Round 2: {p2_name} does the same against {p1_name}'s thesis "
            f"(2-3 sentences)."
        )
        return "\n".join(lines)

    # rounds >= 3 — middle rounds are challenges, final round is closing position.
    for r in range(2, rounds):  # rounds 2..N-1
        lines.append(
            f"  Round {r}: {p1_name} challenges the weakest claim {p2_name} made "
            f"in the previous round (2-3 sentences)."
        )
        lines.append(
            f"  Round {r}: {p2_name} challenges {p1_name}'s previous claim "
            f"(2-3 sentences)."
        )
    # Final round (= N): each closes with a refined position.
    lines.append(
        f"  Round {rounds}: {p1_name} states their final position, "
        f"conceding any genuinely strong counterpoints (2-3 sentences)."
    )
    lines.append(
        f"  Round {rounds}: {p2_name} states their final position similarly "
        f"(2-3 sentences)."
    )
    return "\n".join(lines)


def run_debate(
    request: ResearchRequest,
    shared_data: SharedData,
    personas: list[str],
    *,
    debate_rounds: int = 2,
) -> ModuleResult:
    """Run a two-persona debate over ``debate_rounds`` rounds (1..5).

    ``personas`` must be a list of exactly two persona names present in
    PERSONA_REGISTRY; otherwise returns a skipped ModuleResult. The
    ``debate_rounds`` kwarg is clamped to [1, 5]; default 2 preserves
    Phase 2 behavior for legacy callers (Phase 4+ passes
    ``ctx.request.debate_rounds`` explicitly).
    """
    if len(personas) != 2 or not all(p in PERSONA_REGISTRY for p in personas):
        return ModuleResult(
            module_name="debate", persona_used=None, markdown="",
            skipped=True,
            skip_reason=f"debate needs exactly 2 valid personas, got {personas}",
        )

    rounds = max(1, min(5, int(debate_rounds)))

    p1 = PERSONA_REGISTRY[personas[0]]
    p2 = PERSONA_REGISTRY[personas[1]]
    p1_label = p1.name.title()
    p2_label = p2.name.title()

    sector = (shared_data.company_facts or {}).get("sector", "Unknown")

    round_instructions = _build_round_instructions(p1_label, p2_label, rounds)

    prompt = (
        f"You are simulating a {rounds}-round investment debate between two "
        f"famous investors about ticker {request.ticker} ({sector} sector).\n\n"
        f"=== Persona A: {p1_label} ===\n"
        f"{p1.system_addition()}\n\n"
        f"=== Persona B: {p2_label} ===\n"
        f"{p2.system_addition()}\n\n"
        f"Run the debate as follows:\n"
        f"{round_instructions}\n\n"
        f"Format each statement with a markdown bold label like "
        f"`**{p1_label} (Round 1):**` followed by the prose.\n\n"
        f"Finally produce a 1-2 sentence VERDICT identifying which persona made the "
        f"stronger case on this ticker AT THIS MOMENT — given the sector and "
        f"the ticker's profile. Do not split the difference; pick one."
    )

    out = call_research_llm(
        prompt, _DebateTranscript,
        default_factory=lambda: _DebateTranscript(
            transcript=(
                f"**{p1_label}:** debate LLM failed.\n\n"
                f"**{p2_label}:** debate LLM failed."
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
