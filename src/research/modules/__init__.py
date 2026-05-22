"""Analytical modules for the research pipeline.

Each module is a focused unit of analysis: macro context, sector
strength, fundamentals quality, etc. Phase 1 ships 8 LLM-driven
modules + 1 deterministic backtest module. Phase 2 adds persona
variants. ``ALL_MODULES`` is the registry the pipeline orchestrator
iterates over.
"""

from src.research.modules.base import AnalysisModule
from src.research.modules.financials import FinancialsModule
from src.research.modules.fundamentals import FundamentalsModule
from src.research.modules.macro import MacroModule
from src.research.modules.sector import SectorModule
from src.research.modules.sentiment import SentimentModule
from src.research.modules.technical import TechnicalModule
from src.research.modules.valuation import ValuationModule

ALL_MODULES: list[type[AnalysisModule]] = [
    MacroModule,
    SectorModule,
    FundamentalsModule,
    FinancialsModule,
    ValuationModule,
    TechnicalModule,
    SentimentModule,
]

__all__ = [
    "AnalysisModule", "ALL_MODULES",
    "FinancialsModule", "FundamentalsModule",
    "MacroModule", "SectorModule", "SentimentModule",
    "TechnicalModule", "ValuationModule",
]
