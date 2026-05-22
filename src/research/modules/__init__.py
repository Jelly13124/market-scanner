"""Analytical modules for the research pipeline.

Each module is a focused unit of analysis: macro context, sector
strength, fundamentals quality, etc. Phase 1 ships 8 LLM-driven
modules + 1 deterministic backtest module. Phase 2 adds persona
variants. ``ALL_MODULES`` is the registry the pipeline orchestrator
iterates over.
"""

from src.research.modules.base import AnalysisModule

# ALL_MODULES populated by subsequent commits; intentionally empty here
# so importing the package doesn't try to load modules that don't exist
# yet during Task 4. Each module file adds itself in subsequent tasks.
ALL_MODULES: list[type[AnalysisModule]] = []

__all__ = ["AnalysisModule", "ALL_MODULES"]
