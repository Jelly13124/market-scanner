"""PersonaPrompt ABC contract + Buffett implementation as the first
concrete persona. Subsequent personas added in Task 2."""

from __future__ import annotations

import pytest

from src.research.personas import PERSONA_REGISTRY
from src.research.personas.base import PersonaPrompt
from src.research.personas.buffett import BuffettPrompt


class TestPersonaABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            PersonaPrompt()  # type: ignore[abstract]

    def test_concrete_persona_has_name_and_description(self):
        p = BuffettPrompt()
        assert p.name == "buffett"
        assert isinstance(p.description, str) and len(p.description) > 10

    def test_concrete_persona_emits_system_addition(self):
        p = BuffettPrompt()
        sys_add = p.system_addition()
        assert isinstance(sys_add, str)
        # Should reference Buffett-flavored language
        lower = sys_add.lower()
        assert any(kw in lower for kw in ("moat", "owner earnings", "margin of safety"))

    def test_concrete_persona_emits_module_lens(self):
        p = BuffettPrompt()
        # When asked about fundamentals, returns a module-specific lens
        lens = p.module_lens("fundamentals")
        assert isinstance(lens, str)
        # Unknown module returns empty string (no specialization)
        assert p.module_lens("nonexistent_module") == ""


class TestPersonaRegistry:
    def test_buffett_registered(self):
        assert "buffett" in PERSONA_REGISTRY
        assert isinstance(PERSONA_REGISTRY["buffett"], BuffettPrompt)

    def test_registry_keys_match_persona_name(self):
        """Each registered key must match the persona's .name attribute."""
        for key, persona in PERSONA_REGISTRY.items():
            assert key == persona.name, f"Registry key {key} != persona.name {persona.name}"


# Phase 2 Task 2: Test all 7 additional personas
from src.research.personas.burry import BurryPrompt
from src.research.personas.druckenmiller import DruckenmillerPrompt
from src.research.personas.fisher import FisherPrompt
from src.research.personas.graham import GrahamPrompt
from src.research.personas.lynch import LynchPrompt
from src.research.personas.munger import MungerPrompt
from src.research.personas.wood import WoodPrompt


_ALL_PERSONAS = [
    ("buffett", BuffettPrompt),
    ("munger", MungerPrompt),
    ("graham", GrahamPrompt),
    ("fisher", FisherPrompt),
    ("lynch", LynchPrompt),
    ("wood", WoodPrompt),
    ("burry", BurryPrompt),
    ("druckenmiller", DruckenmillerPrompt),
]


@pytest.mark.parametrize("name,cls", _ALL_PERSONAS, ids=[n for n, _ in _ALL_PERSONAS])
def test_each_persona_basics(name, cls):
    p = cls()
    assert p.name == name
    assert isinstance(p.description, str) and len(p.description) > 10
    sys_add = p.system_addition()
    assert isinstance(sys_add, str)
    assert len(sys_add) > 100   # at least a few sentences


def test_registry_has_all_eight():
    expected = {n for n, _ in _ALL_PERSONAS}
    assert set(PERSONA_REGISTRY.keys()) == expected


def test_personas_signature_keywords():
    """Spot-check each persona references its signature analytical concepts.
    Catches accidental prompt swaps."""
    expectations = {
        "munger":        ["roic", "capital", "predictable"],
        "graham":        ["net-net", "graham number", "margin of safety"],
        "fisher":        ["scuttlebutt", "r&d", "long-term"],
        "lynch":         ["garp", "peg", "categor"],   # six-category framework
        "wood":          ["disruptive", "innovation", "exponential"],
        "burry":         ["fcf yield", "deep value", "contrarian"],
        "druckenmiller": ["macro", "asymmetric", "concentrated"],
    }
    for name, keywords in expectations.items():
        prompt = PERSONA_REGISTRY[name].system_addition().lower()
        for kw in keywords:
            assert kw in prompt, f"{name} prompt missing '{kw}'"
