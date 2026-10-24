from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

Action = Literal["buy", "sell", "short", "cover", "hold"]
Arm = Literal["scanner", "random"]

@dataclass
class Decision:
    ticker: str
    action: Action
    quantity: int = 0
    confidence: int | None = None      # PM confidence 0-100; None if the agent path omitted it
    reasoning: str | None = None

@dataclass
class ArmResult:
    arm: Arm
    scan_date: str
    tickers: list[str]
    decisions: dict[str, Decision] = field(default_factory=dict)
    error: str | None = None
