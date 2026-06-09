"""Fixed, immutable train/val/test time split for the self-evolve loop.

Sample isolation is the load-bearing discipline of this engine. The evolution
loop reads **train** (to propose deltas) and **val** (to keep/rollback) only;
**test** is held out and never read inside the loop — it exists solely for a
single, final out-of-sample readout once evolution has stopped.

The windows below are FIXED. Do not widen, shift, or overlap them: moving a
boundary mid-experiment silently leaks future information into the search and
invalidates every result that came before. They are closed intervals
(both endpoints inclusive) and, by construction, mutually exclusive.

This module is pure Python — no network, no pandas, no LLM.

Public surface:

* :data:`SAMPLES` — ``{name: (start_iso, end_iso)}`` for ``train``/``val``/``test``.
* :func:`sample_of` — classify a ``YYYY-MM-DD`` date into its sample, or ``None``.
* :func:`rebalance_dates` — pick the deterministic rebalance days (first trading
  day of each calendar month) within a sample's window from a trading calendar.
"""

from __future__ import annotations

# The immutable split. Closed (inclusive) ISO-date intervals, non-overlapping
# and contiguous: train ends 2021-12-31, val begins 2022-01-01, etc. The test
# window runs long (through 2030) so any future live date reads as "test".
#
# Treat this as a constant. Code that needs a different split is doing a
# different experiment and must not mutate this dict.
SAMPLES: dict[str, tuple[str, str]] = {
    "train": ("2016-01-01", "2021-12-31"),
    "val": ("2022-01-01", "2023-12-31"),
    "test": ("2024-01-01", "2030-12-31"),
}


def sample_of(date: str) -> str | None:
    """Return the sample name a ``YYYY-MM-DD`` date belongs to, else ``None``.

    Classification is by lexicographic comparison of the ISO date string against
    each window's closed ``[start, end]`` bounds — valid because zero-padded
    ``YYYY-MM-DD`` strings sort in chronological order. A date before all
    windows (or otherwise outside every window) returns ``None``.

    The windows are mutually exclusive, so at most one matches; the first hit in
    insertion order (train, val, test) is returned.
    """
    for name, (lo, hi) in SAMPLES.items():
        if lo <= date <= hi:
            return name
    return None


def rebalance_dates(
    sample: str,
    trading_days: list[str],
    *,
    freq: str = "monthly",
) -> list[str]:
    """Deterministic rebalance dates within ``SAMPLES[sample]``'s window.

    Given an **ascending** list of trading-day ISO date strings (a real exchange
    calendar — weekends/holidays already excluded), return the subset that are
    rebalance days for the chosen cadence, restricted to the sample's window.

    For ``freq="monthly"`` (the only supported cadence): the FIRST trading day
    of each calendar month that has any trading day inside the window. This is
    deterministic and depends only on the supplied calendar — no look-ahead, no
    "nearest to month-start" fuzz.

    Pure and total: empty ``trading_days`` (or a calendar with no days in the
    window) returns ``[]``. ``sample`` is validated against :data:`SAMPLES`
    (``KeyError`` if unknown); an unsupported ``freq`` raises ``ValueError``.

    Note: input is assumed ascending (matching the documented contract and the
    rest of the pipeline). The first day seen per ``YYYY-MM`` is taken as that
    month's rebalance day, so ordering of the input is what defines "first".
    """
    lo, hi = SAMPLES[sample]  # KeyError on unknown sample — fail loud.

    if freq != "monthly":
        raise ValueError(f"unsupported rebalance freq {freq!r}; only 'monthly' is supported")

    out: list[str] = []
    seen_months: set[str] = set()
    for day in trading_days:
        if not (lo <= day <= hi):
            continue
        month = day[:7]  # "YYYY-MM"
        if month in seen_months:
            continue
        seen_months.add(month)
        out.append(day)
    return out
