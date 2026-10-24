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
from src.research.personas.burry import BurryPrompt
from src.research.personas.druckenmiller import DruckenmillerPrompt
from src.research.personas.fisher import FisherPrompt
from src.research.personas.graham import GrahamPrompt
from src.research.personas.lynch import LynchPrompt
from src.research.personas.munger import MungerPrompt
from src.research.personas.wood import WoodPrompt

PERSONA_REGISTRY: dict[str, PersonaPrompt] = {
    "buffett":       BuffettPrompt(),
    "munger":        MungerPrompt(),
    "graham":        GrahamPrompt(),
    "fisher":        FisherPrompt(),
    "lynch":         LynchPrompt(),
    "wood":          WoodPrompt(),
    "burry":         BurryPrompt(),
    "druckenmiller": DruckenmillerPrompt(),
}

__all__ = [
    "PERSONA_REGISTRY", "PersonaPrompt",
    "BuffettPrompt", "BurryPrompt", "DruckenmillerPrompt",
    "FisherPrompt", "GrahamPrompt", "LynchPrompt",
    "MungerPrompt", "WoodPrompt",
]
