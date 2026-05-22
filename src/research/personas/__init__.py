"""Investor persona prompt fragments for persona-capable modules.

The PERSONA_REGISTRY is keyed by persona.name. The persona-router
(src/research/router.py) emits assignment names from this set; modules
look them up here to get the prompt fragment.

Phase 2 ships 8 personas. The registry is intentionally hand-maintained
(not auto-discovered) so the router's output set stays explicit and
easy to validate.
"""

from src.research.personas.base import PersonaPrompt
from src.research.personas.buffett import BuffettPrompt

PERSONA_REGISTRY: dict[str, PersonaPrompt] = {
    "buffett": BuffettPrompt(),
}

__all__ = ["PERSONA_REGISTRY", "PersonaPrompt", "BuffettPrompt"]
