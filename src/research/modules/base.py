"""Base class for analytical modules.

Every module exposes:
  * ``name`` (str) — stable identifier used in logs and module_results
  * ``supports_personas`` (list[str]) — empty = objective only; non-empty
    enumerates which persona prompts the module understands
  * ``run(request, persona, shared_data)`` — returns a ModuleResult

The persona-router (Phase 2) writes ``persona_assignments[name]`` from
the supports_personas list. In Phase 1, persona is always None.

Modules MUST NOT raise — on missing/insufficient data, return a
ModuleResult with ``skipped=True`` and a ``skip_reason``. The pipeline
orchestrator surfaces skipped modules in the report but does not abort.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.research.models import ModuleResult, ResearchRequest
from src.research.shared_data import SharedData


class AnalysisModule(ABC):
    """Abstract base for one analytical section."""

    name: str = "base"
    supports_personas: list[str] = []  # empty = objective only

    @abstractmethod
    def run(
        self,
        request: ResearchRequest,
        persona: str | None,
        shared_data: SharedData,
    ) -> ModuleResult:
        """Produce one ModuleResult. Must not raise; on insufficient data
        return ModuleResult(..., skipped=True, skip_reason='...').
        """
        ...

    def _coerce_persona(self, persona: str | None) -> str | None:
        """Validate persona is in supports_personas; coerce to None
        otherwise. Modules call this at the top of run() to defend
        against a misconfigured router."""
        if persona is None:
            return None
        if persona in self.supports_personas:
            return persona
        return None
