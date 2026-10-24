"""Base class for investor persona prompt fragments.

A persona is a reusable analytical lens that any persona-capable module
(fundamentals, valuation, risk_position) can prepend to its LLM prompt
to shift the analytical voice from objective to character-driven.

Each persona ships:
  * ``name`` — stable identifier (lowercase, no spaces). The router
    emits this string in its assignments JSON.
  * ``description`` — one-line summary for the CLI / report footer.
  * ``system_addition()`` — prompt fragment prepended to the LLM system
    role. Establishes the persona's framework and voice.
  * ``module_lens(module_name)`` — optional per-module specialization
    (e.g., Buffett's "owner earnings" angle for valuation vs his
    "moat strength" angle for fundamentals). Returns empty string when
    the persona has no module-specific guidance.

Refusal / abstain logic does NOT live on the persona. The router
decides who engages based on the ticker profile; modules blindly apply
whatever persona the router picked. Single source of truth.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class PersonaPrompt(ABC):
    """Abstract base for an investor persona prompt fragment."""

    name: str = "base"
    description: str = "abstract persona"

    @abstractmethod
    def system_addition(self) -> str:
        """Persona's analytical framework + voice as a prompt fragment.

        Prepended to the LLM's system role by persona-capable modules.
        Should be 3-6 sentences. Cite the persona's signature techniques.
        """
        ...

    def module_lens(self, module_name: str) -> str:
        """Optional per-module specialization. Default: no specialization."""
        return ""
