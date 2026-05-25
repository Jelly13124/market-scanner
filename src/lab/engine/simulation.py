"""Phase 6B: per-bar simulation loop.

This module is built up in two parts of the plan:
  - Task 8 (signal_eval) — needs ``Position`` for exit evaluation.
  - Task 10 (this task) — adds Trade, SimulationOutput, run_simulation.

The Position dataclass is defined here first so signal_eval tests can
construct a fake position when exercising eval_exit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Position:
    ticker: str
    entry_date: datetime
    entry_price: float
    shares: int
    highest_close: float  # for trailing_stop
