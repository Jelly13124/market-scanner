"""Bridge from a :class:`ScannerEvolveConfig` to live detector instances.

The scanner self-evolve loop tunes detector thresholds inside the bounded
:class:`~v2.scanner.evolve.config.ScannerEvolveConfig`. To measure a config's
fitness, the engine needs the *live* detectors those thresholds describe. This
module builds them.

Task 2 scope: ``_detectors_from_config`` only. The scan-replay / A-vs-random
fitness scorer is a later task.
"""

from __future__ import annotations

from v2.scanner.detectors import (
    EventDetector,
    GapDetector,
    HighBreakoutDetector,
    MaCrossDetector,
    RsiDivergenceDetector,
)
from v2.scanner.evolve.config import ScannerEvolveConfig


def _detectors_from_config(config: ScannerEvolveConfig) -> list[EventDetector]:
    """Construct one detector per key in ``config.detectors``, tuned to its params.

    The ``high_breakout`` and ``ma_cross`` lookback windows are *derived* from
    the tuned param rather than left at the detector default: high_breakout
    needs ``window + 2`` trading bars and ma_cross needs ``slow + 2``. At the
    top of their adjustable ranges (window=300, slow=300) the detectors' default
    400-calendar-day fetch yields too few bars and the detector would silently
    return ``None``. ``max(400, param * 2 + 100)`` calendar days guarantees
    enough bars across the whole range.

    An unrecognized detector name raises :class:`ValueError` (the config layer
    already guarantees the 4 names, but fail loud).
    """
    detectors: list[EventDetector] = []
    for name, params in config.detectors.items():
        if name == "high_breakout":
            window = params["window"]
            detectors.append(HighBreakoutDetector(window=window, lookback_days=max(400, window * 2 + 100)))
        elif name == "ma_cross":
            fast = params["fast"]
            slow = params["slow"]
            detectors.append(MaCrossDetector(fast=fast, slow=slow, lookback_days=max(400, slow * 2 + 100)))
        elif name == "gap":
            detectors.append(GapDetector(threshold=params["threshold"]))
        elif name == "rsi_divergence":
            detectors.append(RsiDivergenceDetector(div_window=params["div_window"]))
        else:
            raise ValueError(f"unknown detector name in config.detectors: {name!r}")
    return detectors
