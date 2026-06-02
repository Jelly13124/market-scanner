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

# Import each concrete section module so its SECTION_REGISTRY[name] =
# FooSection() side-effect fires at package-import time. Without these
# imports, the orchestrator finds an empty registry and emits 'section
# not yet implemented' for every slot. Order matches SECTION_ORDER.
from src.research.sections import (  # noqa: E402, F401  (side-effect imports)
    data_health,
    executive_summary,
    evidence_ledger,
    macro,
    sector,
    company_fundamentals,
    financial_statements,
    valuation,
    technical,
    risk_position,
    scenarios,
    conviction,
    event_risk,
    catalyst,
    debate,
    final_strategy,
    missing_data,
)

__all__ = ["SECTION_REGISTRY", "Section"]
