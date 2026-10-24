"""ExecutiveSummary - bullet decision summary. Reads conviction.total_score
from prior section (the second layer of the always-75 fix - the LLM
never independently invents the score)."""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from src.research.llm import (
    call_research_llm, language_instruction, localized_heading, today_context,
)
from src.research.quant_context import (
    QUANT_CONTEXT_DIRECTIVE, build_quant_context,
)
from src.research.models import SectionPayload
from src.research.sections import SECTION_REGISTRY
from src.research.sections.base import Section, SectionContext

logger = logging.getLogger(__name__)


class _ExecOut(BaseModel):
    # The verdict — the impatient-reader takeaway, surfaced as a banner at
    # the top of the report and a card in the Analyze panel.
    recommendation: Literal["strong_buy", "buy", "hold", "sell", "strong_sell"] = Field(
        description="Actionable call: strong_buy / buy / hold / sell / strong_sell"
    )
    confidence_score: int = Field(
        ge=0, le=100,
        description="0-100 confidence in THIS recommendation (not setup quality)",
    )
    overall_view: str = Field(description="1-2 sentence decision summary")
    main_bullish: str
    main_bearish: str
    target_range: str = Field(description="e.g. '$80 / $115 / $160' bear/base/bull")
    strategy_type: str = Field(description="e.g. 'value swing trade'")
    confidence_qualitative: Literal["high", "medium", "low"]
    key_invalidation: str


def _prior_brief(ctx: SectionContext) -> str:
    parts = []
    for k in ("evidence_ledger", "scenarios"):
        p = ctx.prior.get(k)
        if p and not p.skipped and p.markdown:
            parts.append(f"### {k}\n{p.markdown[:800]}")
    return "\n\n".join(parts) or "(no prior content)"


def _conviction_score(ctx: SectionContext) -> int | None:
    p = ctx.prior.get("conviction")
    if not p or p.skipped or not isinstance(p.structured, dict):
        return None
    return p.structured.get("total_score")


def _position_action(score: int | None, lang: str) -> str | None:
    """Map the 0-100 conviction score to a concrete position action on the house
    ladder: >=85 full buy / >70 small buy / 55-70 hold / 40-54 small sell /
    <40 exit. Returns None when there is no score."""
    if score is None:
        return None
    if score >= 85:
        return "全仓买入" if lang == "zh" else "Full position (buy)"
    if score > 70:
        return "小额买入" if lang == "zh" else "Small buy"
    if score >= 55:
        return "持有 / 观望" if lang == "zh" else "Hold"
    if score >= 40:
        return "小额卖出 / 减仓" if lang == "zh" else "Small sell / trim"
    return "清仓" if lang == "zh" else "Exit / liquidate"


_TASK_INSTRUCTION = (
    "Write the Executive Summary. Output these fields:\n"
    "  recommendation — the single actionable call, exactly one of: "
    "strong_buy, buy, hold, sell, strong_sell. Base it on the balance of "
    "the bullish vs bearish evidence and the risk/reward.\n"
    "  confidence_score — integer 0-100, how confident you are in THIS "
    "recommendation given the evidence quality and agreement across "
    "sections (this is NOT the conviction setup-quality score).\n"
    "  overall_view (1-2 sentence decision summary), main_bullish, "
    "main_bearish, target_range (bear/base/bull dollar ranges), "
    "strategy_type, confidence_qualitative (high/medium/low), "
    "key_invalidation. Do NOT invent a conviction score - that is pulled "
    "from the prior conviction section by the runner."
)


class ExecutiveSummarySection(Section):
    name = "executive_summary"
    supports_personas = []

    def run(self, ctx: SectionContext) -> SectionPayload:
        lang = ctx.request.report_language
        prompt = (
            build_quant_context(ctx.shared, ctx.request.ticker)
            + QUANT_CONTEXT_DIRECTIVE
            + today_context(getattr(ctx.shared, "scan_date", None))
            + language_instruction(lang)
            + _TASK_INSTRUCTION
            + f"\n\nTicker: {ctx.request.ticker}\n"
            + f"Objective: {ctx.request.objective}\n\n"
            + "--- PRIOR ---\n"
            + _prior_brief(ctx)
        )
        heading = localized_heading("## Executive Summary", lang)
        try:
            out = call_research_llm(
                prompt, _ExecOut,
                default_factory=lambda: _ExecOut(
                    recommendation="hold", confidence_score=0,
                    overall_view="LLM failed; no summary.",
                    main_bullish="n/a", main_bearish="n/a",
                    target_range="n/a", strategy_type="n/a",
                    confidence_qualitative="low", key_invalidation="n/a",
                ),
                api_keys=ctx.api_keys,
            )
        except Exception as e:
            logger.exception("executive_summary raised: %s", e)
            return SectionPayload(
                name=self.name,
                markdown=f"{heading}\n\n_unavailable_\n",
                structured=None, skipped=True, persona_used=None,
                skip_reason=str(e),
            )

        score = _conviction_score(ctx)
        rec_label_en = {
            "strong_buy": "Strong Buy", "buy": "Buy", "hold": "Hold",
            "sell": "Sell", "strong_sell": "Strong Sell",
        }
        rec_label_zh = {
            "strong_buy": "强力买入", "buy": "买入", "hold": "持有/观望",
            "sell": "卖出", "strong_sell": "强力卖出",
        }
        rec_display = (rec_label_zh if lang == "zh" else rec_label_en).get(
            out.recommendation, out.recommendation
        )
        L = {
            "recommend":  "投资建议"        if lang == "zh" else "Recommendation",
            "overall":    "总体观点"        if lang == "zh" else "Overall view",
            "bullish":    "主要看多论点"    if lang == "zh" else "Main bullish argument",
            "bearish":    "主要看空风险"    if lang == "zh" else "Main bearish risk",
            "target":     "熊/基准/牛 目标区间" if lang == "zh" else "Bear/base/bull target range",
            "strategy":   "策略类型"        if lang == "zh" else "Strategy type",
            "confidence": "置信度"          if lang == "zh" else "Confidence",
            "invalidate": "关键证伪条件"    if lang == "zh" else "Key invalidation",
            "score":      "信念评分"        if lang == "zh" else "Score",
            "position":   "建议仓位"        if lang == "zh" else "Position action",
        }
        score_line = f"- **{L['score']}:** {score}/100\n" if score is not None else ""
        action = _position_action(score, lang)
        position_line = f"- **{L['position']}:** {action}\n" if action else ""

        md = (
            f"{heading}\n\n"
            f"- **{L['recommend']}:** {rec_display} "
            f"({L['confidence']} {out.confidence_score}/100)\n"
            f"- **{L['overall']}:** {out.overall_view}\n"
            f"- **{L['bullish']}:** {out.main_bullish}\n"
            f"- **{L['bearish']}:** {out.main_bearish}\n"
            f"- **{L['target']}:** {out.target_range}\n"
            f"- **{L['strategy']}:** {out.strategy_type}\n"
            f"- **{L['confidence']}:** {out.confidence_qualitative}\n"
            f"- **{L['invalidate']}:** {out.key_invalidation}\n"
            f"{score_line}"
            f"{position_line}"
        )
        return SectionPayload(
            name=self.name, markdown=md,
            structured={**out.model_dump(), "score_from_conviction": score, "position_action": action},
            skipped=False, persona_used=None,
        )


SECTION_REGISTRY["executive_summary"] = ExecutiveSummarySection()
