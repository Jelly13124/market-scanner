"""Zero-risk live paper-trading harness.

Public surface:
- ``BrokerClient``: the broker Protocol every implementation satisfies.
- ``FakeBroker``: a deterministic in-memory broker for offline tests.
- ``AlpacaBroker``: live placeholder (filled in Task 8).
- ``compute_targets`` / ``SLEEVE_NAMES``: per-sleeve target-position logic.
"""

from __future__ import annotations

from src.paper_trading.broker import AlpacaBroker, BrokerClient, FakeBroker
from src.paper_trading.sleeves import SLEEVE_NAMES, compute_targets

__all__ = [
    "BrokerClient",
    "FakeBroker",
    "AlpacaBroker",
    "compute_targets",
    "SLEEVE_NAMES",
]
