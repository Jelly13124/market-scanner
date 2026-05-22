"""Analytical modules for the research pipeline.

Each module is a focused unit of analysis: macro context, sector
strength, fundamentals quality, etc. Phase 1 ships 8 LLM-driven
modules + 1 deterministic backtest module. Phase 2 adds persona
variants. ``ALL_MODULES`` is the registry the pipeline orchestrator
iterates over.
"""

from src.research.modules.base import AnalysisModule
from src.research.modules.macro import MacroModule

ALL_MODULES: list[type[AnalysisModule]] = [
    MacroModule,
]

__all__ = ["AnalysisModule", "ALL_MODULES", "MacroModule"]
