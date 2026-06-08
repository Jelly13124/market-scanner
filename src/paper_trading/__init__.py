"""Zero-risk live paper-trading harness.

Public surface:
- ``BrokerClient``: the broker Protocol every implementation satisfies.
- ``FakeBroker``: a deterministic in-memory broker for offline tests.
- ``AlpacaBroker``: live placeholder (filled in Task 8).
"""

from __future__ import annotations

from src.paper_trading.broker import AlpacaBroker, BrokerClient, FakeBroker

__all__ = ["BrokerClient", "FakeBroker", "AlpacaBroker"]
