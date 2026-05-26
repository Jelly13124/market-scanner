"""Quantitative signal registry.

Concrete signals subclass ``BaseSignal`` and are registered in
``SIGNAL_REGISTRY`` and ``ALL_SIGNALS``. The scanner instantiates one of
each per scan and passes the per-worker ``DataClient`` to each signal's
``compute()`` call.
"""

from __future__ import annotations

from v2.signals.base import BaseSignal
from v2.signals.earnings_quality import EarningsQualitySignal
from v2.signals.momentum import MomentumSignal
from v2.signals.quality import QualitySignal
from v2.signals.technical import TechnicalSignal
from v2.signals.value import ValueSignal

SIGNAL_REGISTRY: dict[str, type[BaseSignal]] = {
    MomentumSignal.name: MomentumSignal,
    ValueSignal.name: ValueSignal,
    QualitySignal.name: QualitySignal,
    EarningsQualitySignal.name: EarningsQualitySignal,
    TechnicalSignal.name: TechnicalSignal,
}

# Default instantiation list — order matches scoring.factor_weights.
ALL_SIGNALS: list[type[BaseSignal]] = [
    MomentumSignal,
    ValueSignal,
    QualitySignal,
    EarningsQualitySignal,
    TechnicalSignal,
]

__all__ = [
    "BaseSignal",
    "MomentumSignal",
    "ValueSignal",
    "QualitySignal",
    "EarningsQualitySignal",
    "TechnicalSignal",
    "SIGNAL_REGISTRY",
    "ALL_SIGNALS",
]
