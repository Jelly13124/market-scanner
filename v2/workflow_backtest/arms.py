"""A/B backtest arms — scanner-selected vs seeded-random ticker baskets.

``scanner_arm`` runs the v2 scanner and returns its top-N tickers plus the
per-ticker ``scanner_context`` the agent workflow consumes. ``random_arm``
returns a seeded, reproducible random sample from the universe — the control
group whose PM decisions we compare against the scanner's picks.
"""

from __future__ import annotations

import random

from v2.scanner.runner import run_scan as _run_scan


def _scanner_context_for(entry, scan_date):
    """Return ``{ticker: <context dict>}`` for one scored entry.

    Prefers the orchestrator's ``_entry_to_scanner_context`` (which returns the
    bare inner context dict) and wraps it under the ticker key. Falls back to an
    inline equivalent if the import fails for any reason.
    """
    ticker = entry.ticker
    try:
        from v2.pipeline.orchestrator import _entry_to_scanner_context

        ctx = _entry_to_scanner_context(entry, scan_date)
        # Normalise: real helper returns the bare inner dict; if a variant ever
        # returns the already-keyed {ticker: {...}} form, pass it through.
        if ticker in ctx and isinstance(ctx[ticker], dict):
            return ctx
        return {ticker: ctx}
    except Exception:
        triggers = getattr(entry, "triggers", []) or []
        names = [t.get("detector") or t.get("name") for t in triggers if isinstance(t, dict)]
        return {ticker: {
            "scan_date": scan_date,
            "rank": getattr(entry, "rank", 0),
            "composite_score": getattr(entry, "composite_score", 0.0),
            "direction": getattr(entry, "direction", "neutral"),
            "event_severity": getattr(entry, "event_severity", 0.0),
            "triggered_detectors": [n for n in names if n],
            "triggered_components": [],
        }}


def scanner_arm(*, scan_date, universe_tickers, top_n, provider_factory, run_scan_fn=None):
    """Scanner arm: run the scan, return ``(tickers, scanner_context)``.

    ``run_scan_fn`` is a test seam — production callers leave it None and get
    the real ``v2.scanner.runner.run_scan``.
    """
    fn = run_scan_fn or _run_scan
    entries = fn(tickers=universe_tickers, end_date=scan_date, top_n=top_n, provider_factory=provider_factory)
    tickers = [e.ticker for e in entries]
    context = {}
    for e in entries:
        context.update(_scanner_context_for(e, scan_date))
    return tickers, context


def random_arm(*, scan_date, universe_tickers, n, seed):
    """Control arm: a seeded, reproducible random sample of the universe.

    Seeding on ``f"{seed}:{scan_date}"`` makes each scan date independently
    reproducible while still varying across dates for the same base seed.
    Dedupes the universe first so a repeated ticker can't be sampled twice.
    """
    rng = random.Random(f"{seed}:{scan_date}")
    pool = list(dict.fromkeys(universe_tickers))
    return rng.sample(pool, min(n, len(pool)))
