"""Per-sleeve long-only target-position logic for the paper-trading harness.

A *sleeve* is one arm of the live A/B forward test. Given a scan date, each
sleeve answers a single question: "which tickers should we hold this week?"

- ``scanner_agent``: scanner picks → agent → long only the agent's ``buy`` calls.
- ``scanner_only``: scanner picks → long all of them.
- ``spy_benchmark``: ignore the scan and hold ``SPY``.

This module is intentionally decoupled from the real scanner and agent: both
are passed in as injected seam functions so the logic is unit-testable offline
with trivial stubs. The live wiring (mirroring ``run_scan`` /
``run_agents_only``) is added in a later task.

Seam contracts (injected by the caller):

- ``run_scan_fn(scan_date: str, top_n: int) -> list[str]``
      Up to ``top_n`` ranked ticker symbols, best first.
- ``agent_fn(tickers: list[str], scan_date: str) -> dict[str, dict]``
      ``{ticker: {"action": "buy" | "short" | "hold" | ..., ...}}``. This is a
      long-only system, so only ``action == "buy"`` survives.

Invariant: ``compute_targets`` NEVER raises. Any missing data or seam failure
collapses to "no conviction this week" (``[]``); ``spy_benchmark`` always
returns ``["SPY"]`` because it does not depend on the scan.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# The three live A/B sleeves, in a stable order for later tasks to iterate.
SLEEVE_NAMES: tuple[str, ...] = ("scanner_agent", "scanner_only", "spy_benchmark")

RunScanFn = Callable[[str, int], "Optional[list[str]]"]
AgentFn = Callable[[list[str], str], "Optional[dict[str, dict]]"]


def _dedupe_preserving_order(tickers: list[str]) -> list[str]:
    """Drop duplicates while keeping first-seen (rank) order."""
    return list(dict.fromkeys(tickers))


def _safe_scan(run_scan_fn: RunScanFn, scan_date: str, top_n: int) -> list[str]:
    """Call ``run_scan_fn``, normalising failures/None to an empty list.

    Returns deduped tickers capped at ``top_n`` (the seam is contracted to cap
    already, but we enforce it here so a misbehaving stub can't widen the
    basket).
    """
    try:
        raw = run_scan_fn(scan_date, top_n)
    except Exception:
        logger.exception("run_scan_fn raised for scan_date=%s; treating as empty", scan_date)
        return []
    if not raw:
        return []
    return _dedupe_preserving_order(list(raw))[:top_n]


def compute_targets(
    sleeve_name: str,
    scan_date: str,
    *,
    run_scan_fn: RunScanFn,
    agent_fn: AgentFn | None = None,
    top_n: int = 5,
) -> list[str]:
    """Return the long target tickers for ``sleeve_name`` on ``scan_date``.

    Args:
        sleeve_name: One of ``SLEEVE_NAMES``. Anything else yields ``[]``.
        scan_date: The scan as-of date (``YYYY-MM-DD``), passed to the seams.
        run_scan_fn: Injected scanner seam (see module docstring).
        agent_fn: Injected agent seam. Required for ``scanner_agent``; ignored
            by the other sleeves.
        top_n: Max number of ranked picks to request from the scan.

    Returns:
        Target tickers (deduped, rank order preserved). Never raises.
    """
    if sleeve_name == "spy_benchmark":
        # Benchmark does not depend on the scan.
        return ["SPY"]

    if sleeve_name == "scanner_only":
        return _safe_scan(run_scan_fn, scan_date, top_n)

    if sleeve_name == "scanner_agent":
        tickers = _safe_scan(run_scan_fn, scan_date, top_n)
        if not tickers:
            return []
        if agent_fn is None:
            logger.warning(
                "scanner_agent sleeve called without agent_fn for scan_date=%s; treating as no conviction",
                scan_date,
            )
            return []
        try:
            decisions = agent_fn(tickers, scan_date) or {}
        except Exception:
            logger.exception("agent_fn raised for scan_date=%s; treating as no conviction", scan_date)
            return []
        # Keep only buys, preserving scan rank order; dedupe defensively.
        buys = [t for t in tickers if isinstance(decisions.get(t), dict) and decisions[t].get("action") == "buy"]
        return _dedupe_preserving_order(buys)

    logger.warning("unknown sleeve_name=%r; returning no targets", sleeve_name)
    return []
