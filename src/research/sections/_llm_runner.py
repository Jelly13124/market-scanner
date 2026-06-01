"""Shared LLM dispatch for SOP sections."""

from __future__ import annotations

import logging
from typing import TypeVar

from pydantic import BaseModel

from src.research.llm import (
    call_research_llm, language_instruction, localized_heading, today_context,
)
from src.research.models import SectionPayload
from src.research.personas import PERSONA_REGISTRY
from src.research.quant_context import (
    QUANT_CONTEXT_DIRECTIVE, build_quant_context,
)
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
    # Phase 11: inject the comprehensive QUANT CONTEXT block (current
    # price, indicators, fundamentals, news) followed by the
    # anti-hallucination directive. Placed before the section's task
    # prompt so the LLM sees real numbers BEFORE the question.
    quant_block = build_quant_context(ctx.shared, ctx.request.ticker)
    final = quant_block + QUANT_CONTEXT_DIRECTIVE + "\n" + final
    # Phase 10.5: prepend today's-date context so the LLM doesn't default
    # to its training-cutoff baseline.
    date_prefix = today_context(getattr(ctx.shared, "scan_date", None))
    if date_prefix:
        final = date_prefix + final
    # Phase 7 i18n: prepend language instruction LAST (most-recent-wins
    # for compliance). No-op when report_language == "en".
    lang_prefix = language_instruction(ctx.request.report_language)
    if lang_prefix:
        final = lang_prefix + final
    # Phase 10.5: localize the H2 heading so we don't get half-Chinese
    # half-English when report is requested in zh.
    heading = localized_heading(markdown_heading, ctx.request.report_language)
    try:
        r = call_research_llm(
            final, output_model,
            default_factory=lambda: output_model(
                narrative=f"LLM call failed for {section_name}."
            ),
            api_keys=ctx.api_keys,
        )
        narrative = getattr(r, "narrative", "") or ""
        return SectionPayload(
            name=section_name,
            markdown=f"{heading}\n\n{narrative}\n",
            structured=r.model_dump(),
            skipped=False, persona_used=persona_used,
        )
    except Exception as e:
        logger.exception("section %s raised: %s", section_name, e)
        return SectionPayload(
            name=section_name,
            markdown=f"{heading}\n\n_section unavailable: {e}_\n",
            structured=None, skipped=True, persona_used=persona_used,
            skip_reason=str(e),
        )
