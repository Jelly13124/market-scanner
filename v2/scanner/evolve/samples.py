"""Immutable train / val / test regime-sample isolation for scanner self-evolve.

The scanner self-evolve loop reads ONLY ``train`` + ``val`` when scoring configs.
The held-out ``test`` window is a LATER, distinct span that is read exactly once
*after* the loop terminates — never inside it — so a config can't be tuned to fit
the held-out outcomes.

The three labelled regimes mirror the eval harness's three regimes in
:data:`v2.scanner.eval.regimes.DEFAULT_CANDIDATES`:

    * ``bear_2022``     2022-01-03 .. 2022-10-14
    * ``bull_2023_24``  2023-10-27 .. 2024-07-16
    * ``choppy_2025``   2025-02-18 .. 2025-08-01

``train`` = (bear_2022, bull_2023_24); ``val`` = (choppy_2025,). The dates are
restated here (not imported) so this module is self-contained; keep them in sync
with ``DEFAULT_CANDIDATES`` — ``test_samples.py`` asserts they match.

The ``test`` window ``heldout_2025_26`` (2025-09-01 .. 2026-06-01) starts after
choppy_2025 ends (2025-08-01), so it does NOT overlap any train/val window.

``SAMPLES`` is IMMUTABLE: a :class:`~types.MappingProxyType` over a dict of
tuples-of-:class:`RegimeSpan`. Neither the mapping nor the per-sample window
tuples can be mutated by a caller; ``window_of`` hands back a fresh ``list`` so
even mutating *that* can't corrupt ``SAMPLES``.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import NamedTuple


class RegimeSpan(NamedTuple):
    """One named regime window with an inclusive ``[start, end]`` date span."""

    name: str  # e.g. "bear_2022"
    start: str  # YYYY-MM-DD
    end: str  # YYYY-MM-DD


# Train/val mirror DEFAULT_CANDIDATES (restated, keep in sync). Test is held out.
_BEAR_2022 = RegimeSpan("bear_2022", "2022-01-03", "2022-10-14")
_BULL_2023_24 = RegimeSpan("bull_2023_24", "2023-10-27", "2024-07-16")
_CHOPPY_2025 = RegimeSpan("choppy_2025", "2025-02-18", "2025-08-01")
# Held-out: starts after choppy_2025 ends (2025-08-01) → no overlap with train/val.
_HELDOUT_2025_26 = RegimeSpan("heldout_2025_26", "2025-09-01", "2026-06-01")


#: IMMUTABLE mapping ``sample -> tuple[RegimeSpan, ...]``. The loop reads only
#: train+val; test is read once post-loop.
SAMPLES: MappingProxyType = MappingProxyType(
    {
        "train": (_BEAR_2022, _BULL_2023_24),
        "val": (_CHOPPY_2025,),
        "test": (_HELDOUT_2025_26,),
    }
)


def window_of(sample: str) -> list[tuple[str, str]]:
    """Return ``[(start, end), ...]`` for the named sample.

    Hands back a fresh ``list`` of ``(start, end)`` tuples so mutating the result
    can never corrupt :data:`SAMPLES`. Raises :class:`KeyError` for an unknown
    sample name — fail loud, never a silent empty list.
    """
    if sample not in SAMPLES:
        raise KeyError(f"unknown sample {sample!r}; expected one of {sorted(SAMPLES)}")
    return [(w.start, w.end) for w in SAMPLES[sample]]


def sample_of(date: str) -> str | None:
    """Return the sample name whose window(s) contain ``date``, else ``None``.

    Inclusive bounds (``start <= date <= end``), compared as ``YYYY-MM-DD``
    strings (lexicographic order is chronological for that format). The windows
    are disjoint, so at most one sample matches.
    """
    day = date[:10]
    for sample, spans in SAMPLES.items():
        for w in spans:
            if w.start <= day <= w.end:
                return sample
    return None
