"""Conviction / Setup Quality Score - 6-category weighted score.

FIXES the 'always 75/100' bug from Phase 1-3: total_score is computed
DETERMINISTICALLY as sum(weight * score / 100) across 6 categories.
The LLM only scores each category individually (0-100); it never
emits the total.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from src.research.llm import (
    call_research_llm, language_instruction, localized_heading, today_context,
)
from src.research.models import SectionPayload
from src.research.sections import SECTION_REGISTRY
from src.research.sections.base import Section, SectionContext

logger = logging.getLogger(__name__)


_CATEGORIES = (
    "macro_sector_environment",
    "company_fundamentals",
    "valuation_margin_of_safety",
    "technical_setup",
    "risk_event_profile",
    "catalyst_news_quality",
)


# Weights sum to 100 per profile. Profile selected from request.risk_tolerance.
_WEIGHTS = {
    "conservative": (15, 25, 25, 10, 15, 10),
    "balanced":     (15, 25, 20, 15, 15, 10),
    "aggressive":   (10, 20, 20, 25, 15, 10),
}


class _CategoryScore(BaseModel):
    name: str
    score: int = Field(ge=0, le=100)
    rationale: str


class _ConvictionOut(BaseModel):
    categories: list[_CategoryScore] = Field(min_length=6, max_length=6)


_TASK_INSTRUCTION = (
    "Score this ticker across 6 conviction categories. Each score is "
    "0-100 (NOT a percentage of weight). Output EXACTLY 6 categories "
    "in this order:\n"
    "  1) macro_sector_environment\n"
    "  2) company_fundamentals\n"
    "  3) valuation_margin_of_safety\n"
    "  4) technical_setup\n"
    "  5) risk_event_profile\n"
    "  6) catalyst_news_quality\n"
    "Each item: name (use exact slug above), score (0-100 integer), "
    "rationale (1-2 sentences). The TOTAL score will be computed "
    "deterministically as sum(weight * score / 100) by the runner — "
    "do NOT output a total."
)


def _prior_summary(ctx: SectionContext) -> str:
    parts = []
    for k in ("macro", "sector", "company_fundamentals", "valuation",
              "technical", "risk_position", "event_risk"):
        p = ctx.prior.get(k)
        if p and not p.skipped and p.markdown:
            parts.append(f"### {k}\n{p.markdown[:500]}")
    return "\n\n".join(parts) or "(no prior content)"


class ConvictionSection(Section):
    name = "conviction"
    supports_personas = []

    def run(self, ctx: SectionContext) -> SectionPayload:
        lang = ctx.request.report_language
        weights = _WEIGHTS.get(ctx.request.risk_tolerance, _WEIGHTS["balanced"])
        prompt = (
            today_context(getattr(ctx.shared, "scan_date", None))
            + language_instruction(lang)
            + _TASK_INSTRUCTION
            + f"\n\nTicker: {ctx.request.ticker}\n"
            + f"Risk profile (for weight column): {ctx.request.risk_tolerance}\n\n"
            + "--- PRIOR SECTION SUMMARIES ---\n"
            + _prior_summary(ctx)
        )
        heading = localized_heading("## Conviction / Setup Quality Score", lang)
        try:
            out = call_research_llm(
                prompt, _ConvictionOut,
                default_factory=lambda: _ConvictionOut(categories=[
                    _CategoryScore(name=c, score=0, rationale="LLM failed")
                    for c in _CATEGORIES
                ]),
            )
        except Exception as e:
            logger.exception("conviction raised: %s", e)
            return SectionPayload(
                name=self.name,
                markdown=f"{heading}\n\n_unavailable_\n",
                structured=None, skipped=True, persona_used=None,
                skip_reason=str(e),
            )

        # Align LLM categories to our canonical order; missing → score=0
        by_name = {c.name: c for c in out.categories}
        ordered = []
        for slug in _CATEGORIES:
            if slug in by_name:
                ordered.append(by_name[slug])
            else:
                ordered.append(_CategoryScore(
                    name=slug, score=0,
                    rationale="LLM did not score this category",
                ))

        # DETERMINISTIC weighted total — the always-75 fix
        total_score = sum(w * c.score / 100 for w, c in zip(weights, ordered))
        total_score = int(round(total_score))

        if lang == "zh":
            rows = [
                "| 类别 | 权重 | 得分 0-100 | 理由 |",
                "|---|---:|---:|---|",
            ]
            total_label, note = "合计", "（加权）"
            risk_intro = f"采用风险偏好画像：**{ctx.request.risk_tolerance}**"
            score_line = f"**总分: {total_score}/100**"
        else:
            rows = [
                "| Category | Weight | Score 0-100 | Rationale |",
                "|---|---:|---:|---|",
            ]
            total_label, note = "Total", "(weighted)"
            risk_intro = f"Risk-tolerance profile applied: **{ctx.request.risk_tolerance}**"
            score_line = f"**Score: {total_score}/100**"
        for w, c in zip(weights, ordered):
            rows.append(f"| {c.name} | {w} | {c.score} | {c.rationale} |")
        rows.append(f"| **{total_label}** | **100** | **{total_score}** | {note} |")
        md = (
            f"{heading}\n\n"
            + risk_intro + "\n\n"
            + "\n".join(rows)
            + f"\n\n{score_line}\n"
        )
        return SectionPayload(
            name=self.name, markdown=md,
            structured={
                "categories": [c.model_dump() for c in ordered],
                "weights": list(weights),
                "total_score": total_score,
                "risk_profile": ctx.request.risk_tolerance,
            },
            skipped=False, persona_used=None,
        )


SECTION_REGISTRY["conviction"] = ConvictionSection()
