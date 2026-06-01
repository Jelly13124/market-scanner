"""SOP Section abstract base + execution context.

Each Section is a self-contained LLM runner: it builds its own prompt
from the SectionContext (request + shared data + earlier sections'
outputs), calls call_research_llm, and emits a SectionPayload. The
orchestrator iterates SECTION_ORDER and calls each registered Section.

Sections downstream of upstream ones can read prior outputs via
SectionContext.prior - e.g. ExecutiveSummary reads EvidenceLedger's
structured list before writing its bullet decision-summary.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from src.research.models import AnalyzeRequest, SectionPayload
from src.research.shared_data import SharedData


_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def load_prompt(relative: str) -> str:
    """Read one of the vendored skill prompt files. Returns the
    markdown text; raises FileNotFoundError if missing (forces a clear
    error rather than a silently empty prompt)."""
    return (_PROMPTS_DIR / relative).read_text(encoding="utf-8")


@dataclass
class SectionContext:
    """Everything a Section runner needs to produce its payload."""
    request: AnalyzeRequest
    shared: SharedData
    persona: str | None
    prior: dict[str, SectionPayload]
    # Per-user API keys (multi-tenant): forwarded to call_research_llm so
    # each request uses the requesting user's own provider keys. None =>
    # fall back to host-env keys (single-tenant / legacy behavior).
    api_keys: dict | None = None


class Section(ABC):
    """Abstract SOP section runner.

    Subclasses override:
      * ``name`` - matches SECTION_ORDER entries
      * ``supports_personas`` - list of persona names that can shade
        this section (most sections empty; fundamentals/valuation/
        risk_position support personas, matching Phase 2)
      * ``run(ctx)`` - produce SectionPayload
    """
    name: str = "base"
    supports_personas: list[str] = []

    @abstractmethod
    def run(self, ctx: SectionContext) -> SectionPayload:
        ...
