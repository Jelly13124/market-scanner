"""Per-stock research pipeline (Phase 1: core).

Public types live in ``src.research.models``. Pipeline entry-point is
``src.research.pipeline.run_research``. CLI: ``python -m src.research``.

This package is intentionally isolated from ``src/agents/`` (the legacy
portfolio pipeline). Both live in parallel; the scanner feeds both.
"""

from src.research.models import (
    BacktestSummary,
    ModuleResult,
    ResearchRequest,
    ResearchState,
    TradePlan,
)

__all__ = [
    "BacktestSummary",
    "ModuleResult",
    "ResearchRequest",
    "ResearchState",
    "TradePlan",
]
