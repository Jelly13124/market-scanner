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
