"""SOP section registry. Each concrete Section subclass registers
itself by adding to SECTION_REGISTRY at import time.

The orchestrator imports this module and dispatches in SECTION_ORDER
(from src.research.models), looking up each name in SECTION_REGISTRY.
Missing entries -> 'n/a - not implemented' SectionPayload, so partial
delivery is acceptable during the Phase 4 rollout.
"""

from __future__ import annotations

from src.research.sections.base import Section

SECTION_REGISTRY: dict[str, Section] = {}

__all__ = ["SECTION_REGISTRY", "Section"]
