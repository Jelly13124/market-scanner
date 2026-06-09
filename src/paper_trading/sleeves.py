"""Per-sleeve long-only target-position logic for the paper-trading harness.

A *sleeve* is one arm of the live A/B forward test. Given a scan date, each
sleeve answers a single question: "which tickers should we hold this week?"

- ``scanner_agent``: scanner picks → agent → long only the agent's ``buy`` calls.
- ``scanner_only``: scanner picks → long all of them.
- ``spy_benchmark``: ignore the scan and hold ``SPY``.
- ``factor_evolved``: ignore the scanner; hold the best self-evolved factor
  config's book (the injected ``factor_fn`` returns its ticker list).

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
- ``factor_fn(scan_date: str) -> list[str]``
      The ticker book of the best self-evolved factor config (see
      :mod:`v2.self_evolve.graduate`). Used only by ``factor_evolved``.

Invariant: ``compute_targets`` NEVER raises. Any missing data or seam failure
collapses to "no conviction this week" (``[]``); ``spy_benchmark`` always
returns ``["SPY"]`` because it does not depend on the scan.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# The live A/B sleeves, in a stable order for later tasks to iterate.
# ``scanner_agent_flow`` is identical to ``scanner_agent`` (scan -> agent -> buys);
# they differ ONLY in whether the agent runs with institutional-flow context (the
# runner toggles ``set_flow_enabled`` per sleeve), making them a with/without-flow A/B.
#
# ``factor_evolved`` is the graduation sleeve: it ignores the scanner/agent and
# instead holds the book of the best self-evolved factor config (via the injected
# ``factor_fn``), forward-testing the self-evolve loop's output against the rest.
SLEEVE_NAMES: tuple[str, ...] = ("scanner_agent", "scanner_only", "spy_benchmark", "scanner_agent_flow", "factor_evolved")

RunScanFn = Callable[[str, int], "Optional[list[str]]"]
AgentFn = Callable[[list[str], str], "Optional[dict[str, dict]]"]
FactorFn = Callable[[str], "Optional[list[str]]"]


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
    factor_fn: FactorFn | None = None,
    top_n: int = 5,
) -> list[str]:
    """Return the long target tickers for ``sleeve_name`` on ``scan_date``.

    Args:
        sleeve_name: One of ``SLEEVE_NAMES``. Anything else yields ``[]``.
        scan_date: The scan as-of date (``YYYY-MM-DD``), passed to the seams.
        run_scan_fn: Injected scanner seam (see module docstring).
        agent_fn: Injected agent seam. Required for ``scanner_agent``; ignored
            by the other sleeves.
        factor_fn: Injected self-evolved factor seam. Required for
            ``factor_evolved``; ignored by the other sleeves.
        top_n: Max number of ranked picks to request from the scan.

    Returns:
        Target tickers (deduped, rank order preserved). Never raises.
    """
    if sleeve_name == "spy_benchmark":
        # Benchmark does not depend on the scan.
        return ["SPY"]

    if sleeve_name == "factor_evolved":
        # The graduation sleeve: hold the best self-evolved factor config's book.
        # It ignores the scanner/agent entirely — the factor_fn IS the strategy.
        if factor_fn is None:
            logger.warning(
                "factor_evolved sleeve called without factor_fn for scan_date=%s; treating as no conviction",
                scan_date,
            )
            return []
        try:
            raw = factor_fn(scan_date) or []
        except Exception:
            logger.exception("factor_fn raised for scan_date=%s; treating as no conviction", scan_date)
            return []
        # The factor book is already top-N + capped upstream; just dedupe and drop
        # any non-string the seam might emit (defensive, mirrors the scan path).
        return _dedupe_preserving_order([t for t in raw if isinstance(t, str)])

    if sleeve_name == "scanner_only":
        return _safe_scan(run_scan_fn, scan_date, top_n)

    if sleeve_name in ("scanner_agent", "scanner_agent_flow"):
        # Identical logic for both: the flow difference is the runner toggling
        # set_flow_enabled around this call, not a branch here.
        tickers = _safe_scan(run_scan_fn, scan_date, top_n)
        if not tickers:
            return []
        if agent_fn is None:
            logger.warning(
                "%s sleeve called without agent_fn for scan_date=%s; treating as no conviction",
                sleeve_name,
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
