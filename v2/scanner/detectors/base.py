"""Base classes for scanner event detectors.

Why a separate ABC instead of subclassing ``v2.signals.base.BaseSignal``?

``BaseSignal`` answers a different question: directional signal strength in
``[-1, +1]``. Event detectors need to answer: *did anything happen and how
unusual was it?* That's a triggered/severity pair, plus a human-readable reason
for the UI. Detectors are still free to reuse ``BaseSignal``'s static helpers
(``_safe_float``, ``_percentile_rank``, ``_sigmoid``, ``_compute_rsi``).

Module-level helpers below are the ones every detector ended up rewriting
locally before consolidation (``parse_date`` was inlined in 9 files,
``close_of`` in 3).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from v2.data.protocol import DataClient
from v2.scanner.models import Direction, ScanContext


def parse_date(s: str | None) -> date | None:
    """Parse a ``YYYY-MM-DD`` (or longer ISO) prefix into a ``date``.

    Returns ``None`` on missing input or malformed strings — matches the
    "exclude this ticker from stats" convention used by detector ``None``
    returns. Replaces the ~identical ``_parse_date`` inlined in every
    detector before this consolidation.
    """
    if s is None:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def close_of(p) -> float | None:
    """Adjusted-close-preferred read of a ``Price`` bar.

    Returns the split- and dividend-adjusted close when the provider
    supplies it (EODHD does, Finnhub doesn't), otherwise the raw close.
    Returns ``None`` when neither is set. Detectors should always go
    through this rather than ``p.close`` directly — using raw close on
    ex-div / split days produces spurious giant moves.
    """
    if p.adjusted_close is not None:
        return float(p.adjusted_close)
    if p.close is not None:
        return float(p.close)
    return None


class EventTrigger(BaseModel):
    """One detector's verdict on one ticker for one as-of date."""

    detector: str
    triggered: bool
    severity_z: float = 0.0
    direction: Direction = "neutral"
    reason: str = ""
    components: dict[str, float] = Field(default_factory=dict)
    asof_date: str | None = None


class EventDetector(ABC):
    """Abstract event detector.

    Contract:
        ``detect`` returns:
            * ``EventTrigger(triggered=True, ...)``  — event fired
            * ``EventTrigger(triggered=False, ...)`` — ran successfully but nothing fired
            * ``None``                                — could not run (no data, etc.)

        ``None`` is distinct from ``triggered=False``: the latter is signal,
        the former is missing data.
    """

    #: Stable identifier used in EventTrigger.detector and scoring weights.
    name: str = "base"

    @abstractmethod
    def detect(
        self,
        ticker: str,
        end_date: str,
        fd: DataClient,
        *,
        ctx: ScanContext | None = None,
    ) -> EventTrigger | None:
        ...
