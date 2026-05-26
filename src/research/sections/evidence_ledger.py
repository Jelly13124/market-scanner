"""EvidenceLedger - emits >=10 bull/bear/neutral evidence rows as a
markdown table + a structured list. Reads upstream sections from
ctx.prior so the ledger reflects what was actually researched."""

from __future__ import annotations

import html
import logging
from typing import Literal

from pydantic import BaseModel, Field

from src.research.llm import call_research_llm, language_instruction
from src.research.models import SectionPayload
from src.research.sections import SECTION_REGISTRY
from src.research.sections.base import Section, SectionContext, load_prompt

logger = logging.getLogger(__name__)


class _Evidence(BaseModel):
    claim: str
    evidence: str
    source: str
    date: str
    direction: Literal["bullish", "bearish", "neutral", "missing"]
    confidence: Literal["high", "medium", "low"]


class _LedgerOut(BaseModel):
    items: list[_Evidence] = Field(
        default_factory=list,
        description="At least 10 evidence items per SOP minimum gate",
    )


_SYSTEM_PROMPT = load_prompt("modules/macro.md")  # fallback prompt context

# The skill's report_template.md describes the Evidence Ledger structure;
# we inline the instruction here rather than load a dedicated module
# (the skill has no separate evidence_ledger.md prompt).
_TASK_INSTRUCTION = (
    "You are assembling the Evidence Ledger section. Produce at least "
    "10 items (15-20 ideal). Each item: claim (1-line), evidence "
    "(numeric/dated when possible), source, date (YYYY-MM-DD when "
    "known), direction (bullish/bearish/neutral/missing), confidence "
    "(high/medium/low). Use the prior section outputs below to ground "
    "items in real research."
)


def _prior_summary(ctx: SectionContext) -> str:
    out = []
    for name, payload in ctx.prior.items():
        if payload.skipped or not payload.markdown.strip():
            continue
        snippet = payload.markdown[:600]
        out.append(f"### Prior section: {name}\n{snippet}")
    return "\n\n".join(out) if out else "(no prior sections yet)"


class EvidenceLedgerSection(Section):
    name = "evidence_ledger"
    supports_personas = []

    def run(self, ctx: SectionContext) -> SectionPayload:
        prompt = (
            language_instruction(ctx.request.report_language)
            + _TASK_INSTRUCTION
            + f"\n\nTicker: {ctx.request.ticker}\n"
            + f"Objective: {ctx.request.objective}\n\n"
            + "--- PRIOR SECTION CONTENT ---\n"
            + _prior_summary(ctx)
        )
        try:
            out = call_research_llm(
                prompt, _LedgerOut,
                default_factory=lambda: _LedgerOut(items=[]),
            )
        except Exception as e:
            logger.exception("evidence_ledger raised: %s", e)
            return SectionPayload(
                name=self.name,
                markdown="## Evidence Ledger\n\n_unavailable_\n",
                structured=None, skipped=True, persona_used=None,
                skip_reason=str(e),
            )
        rows = [
            "| Claim | Evidence | Source | Date | Direction | Confidence |",
            "|---|---|---|---|---|---|",
        ]
        for it in out.items:
            rows.append(
                f"| {it.claim} | {it.evidence} | {it.source} | "
                f"{it.date} | {it.direction} | {it.confidence} |"
            )
        md = "## Evidence Ledger\n\n" + "\n".join(rows) + "\n"
        return SectionPayload(
            name=self.name, markdown=md,
            structured=[i.model_dump() for i in out.items],
            skipped=False, persona_used=None,
        )


SECTION_REGISTRY["evidence_ledger"] = EvidenceLedgerSection()
