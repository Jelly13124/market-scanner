"""Shared LLM dispatch for SOP sections."""

from __future__ import annotations

import logging
from typing import TypeVar

from pydantic import BaseModel

from src.research.llm import call_research_llm
from src.research.models import SectionPayload
from src.research.personas import PERSONA_REGISTRY
from src.research.sections.base import SectionContext

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


def run_llm_section(
    *, section_name: str, ctx: SectionContext,
    prompt: str, output_model: type[T], markdown_heading: str,
) -> SectionPayload:
    final = prompt
    persona_used: str | None = None
    if ctx.persona is not None:
        p = PERSONA_REGISTRY.get(ctx.persona)
        if p is not None:
            final = (
                p.system_addition() + "\n\n"
                + p.module_lens(section_name) + "\n\n"
                + prompt
            )
            persona_used = ctx.persona
    try:
        r = call_research_llm(
            final, output_model,
            default_factory=lambda: output_model(
                narrative=f"LLM call failed for {section_name}."
            ),
        )
        narrative = getattr(r, "narrative", "") or ""
        return SectionPayload(
            name=section_name,
            markdown=f"{markdown_heading}\n\n{narrative}\n",
            structured=r.model_dump(),
            skipped=False, persona_used=persona_used,
        )
    except Exception as e:
        logger.exception("section %s raised: %s", section_name, e)
        return SectionPayload(
            name=section_name,
            markdown=f"{markdown_heading}\n\n_section unavailable: {e}_\n",
            structured=None, skipped=True, persona_used=persona_used,
            skip_reason=str(e),
        )
