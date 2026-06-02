"""Persona-router — one LLM call decides which investor persona
analyzes each module on this ticker.

Input:
  * ResearchRequest (ticker, holding_status, etc.)
  * SharedData (ticker profile: sector, market_cap, revenue_growth, etc.)

Output:
  dict mapping module name to persona name (str), list of two personas
  (list[str], for debate), or None (objective).

Invalid persona names returned by the LLM are coerced to None for that
module. The debate slot is dropped to [] unless it contains exactly two
valid persona names.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from src.research.llm import call_research_llm
from src.research.models import ResearchRequest
from src.research.personas import PERSONA_REGISTRY
from src.research.shared_data import SharedData

logger = logging.getLogger(__name__)


class _RouterOutput(BaseModel):
    """LLM output: per-module persona assignments + a rationale string."""

    fundamentals: str | None = Field(
        default=None,
        description="Persona for the fundamentals module, or null for objective.",
    )
    valuation: str | None = Field(
        default=None,
        description="Persona for the valuation module, or null for objective.",
    )
    risk_position: str | None = Field(
        default=None,
        description="Persona for the risk_position module, or null for objective.",
    )
    debate: list[str] = Field(
        default_factory=list,
        description=(
            "Either an empty list (no debate) or EXACTLY two persona names "
            "for a two-round debate panel. Three or more is invalid."
        ),
    )
    rationale: str = Field(
        description="1-2 sentence explanation of the assignment choices."
    )


def _ticker_profile(shared: SharedData) -> dict:
    """Distill SharedData into the compact profile the router LLM needs."""
    facts = shared.company_facts or {}
    revenue_growth = 0.0
    profitable = False
    if shared.financials:
        latest = shared.financials[0]
        revenue_growth = float(getattr(latest, "revenue_growth", 0) or 0)
    return {
        "ticker": shared.ticker,
        "sector": facts.get("sector") or facts.get("industry") or "Unknown",
        "market_cap": float(facts.get("market_cap") or 0),
        "revenue_growth": revenue_growth,
        "profitable": profitable,
    }


def route_personas(
    request: ResearchRequest,
    shared: SharedData,
    *,
    api_keys: dict | None = None,
) -> dict[str, str | list[str] | None]:
    """Run the router LLM and return validated per-module assignments.

    Persona names not in PERSONA_REGISTRY are coerced to None.
    Debate list is dropped to [] unless it contains exactly two valid names.
    """
    profile = _ticker_profile(shared)
    triggered = []
    if request.scanner_context:
        triggered = request.scanner_context.get("triggered_detectors") or []

    available = sorted(PERSONA_REGISTRY.keys())
    persona_descriptions = "\n".join(
        f"  * {name}: {PERSONA_REGISTRY[name].description}"
        for name in available
    )

    prompt = (
        f"You are routing investor personas to analytical modules for "
        f"ticker {profile['ticker']}.\n\n"
        f"Ticker profile:\n"
        f"  Sector: {profile['sector']}\n"
        f"  Market cap: ${profile['market_cap'] / 1e9:.1f}B\n"
        f"  Revenue growth (YoY): {profile['revenue_growth'] * 100:+.1f}%\n"
        f"  Scanner triggers: {triggered or 'none'}\n\n"
        f"Available personas:\n{persona_descriptions}\n\n"
        f"Assign a persona to each of: fundamentals, valuation, risk_position.\n"
        f"Use null for any module where no persona is a strong fit (the "
        f"module then runs objective).\n\n"
        f"Optionally pick EXACTLY two personas for a debate slot when their "
        f"frameworks would genuinely disagree on this ticker (e.g., a tech "
        f"growth name might warrant Wood vs Burry). If no two-persona "
        f"debate is justified, return an empty debate list.\n\n"
        f"Also return a 1-2 sentence rationale explaining your choices."
    )

    out = call_research_llm(
        prompt, _RouterOutput,
        default_factory=lambda: _RouterOutput(
            fundamentals=None, valuation=None, risk_position=None,
            debate=[], rationale="Router LLM failed; defaulting to objective.",
        ),
        api_keys=api_keys,
    )

    def _valid(name: str | None) -> str | None:
        if name is None:
            return None
        if name in PERSONA_REGISTRY:
            return name
        logger.warning("Router emitted unknown persona %r; coercing to None", name)
        return None

    debate_valid: list[str] = []
    if (isinstance(out.debate, list) and len(out.debate) == 2
            and all(p in PERSONA_REGISTRY for p in out.debate)):
        debate_valid = list(out.debate)
    elif out.debate:
        logger.warning(
            "Router emitted debate=%r; require exactly 2 valid personas, dropping",
            out.debate,
        )

    return {
        "fundamentals":  _valid(out.fundamentals),
        "valuation":     _valid(out.valuation),
        "risk_position": _valid(out.risk_position),
        "debate":        debate_valid,
        "_rationale":    out.rationale,  # surfaced in report footer
    }
