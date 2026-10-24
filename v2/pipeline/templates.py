"""Named analyst rosters for the scanner→agent pipeline.

A user invoking the bridge picks one of these templates instead of
manually selecting 9-of-20 analysts from a flat list. ``custom_analysts``
on ``run_pipeline`` provides the escape hatch for advanced users.

Each template starts with ``scanner_signal`` (the bridge's own node) so
the scanner's findings are always in the deliberation, then layers a
small set of persona + analyst nodes chosen for the template's archetype.
"""

from __future__ import annotations

from typing import Iterable

# fmt: off
TEMPLATES: dict[str, list[str]] = {
    # The all-rounder default — diverse persona views (value/growth/contrarian)
    # plus 5 objective analyst nodes plus 2 context nodes (macro regime +
    # sector relative strength). Added 2026-05-19: macro/sector inputs
    # give PM portfolio-level + sector-level context as first-class signals.
    "balanced": [
        "scanner_signal",
        "macro_signal", "sector_signal",
        "warren_buffett", "cathie_wood", "michael_burry",
        "fundamentals_analyst", "technical_analyst",
        "valuation_analyst", "sentiment_analyst", "growth_analyst",
    ],
    # Buffett-school value lineup.
    "value": [
        "scanner_signal",
        "warren_buffett", "ben_graham", "charlie_munger", "mohnish_pabrai",
        "fundamentals_analyst", "valuation_analyst",
    ],
    # Growth / disruption lineup.
    "growth": [
        "scanner_signal",
        "cathie_wood", "peter_lynch", "phil_fisher", "stanley_druckenmiller",
        "technical_analyst", "sentiment_analyst", "growth_analyst",
    ],
    # Minimum cost — 5 objective analysts plus the scanner bridge. No persona
    # debate.
    "quick": [
        "scanner_signal",
        "fundamentals_analyst", "technical_analyst",
        "valuation_analyst", "sentiment_analyst",
    ],
}
# fmt: on

DEFAULT_TEMPLATE = "balanced"


def _known_analyst_keys() -> set[str]:
    """Set of valid analyst keys = ANALYST_CONFIG keys (which already
    includes ``scanner_signal`` since Phase 1.2)."""
    # Lazy import so this module stays importable without dragging in the
    # whole agent stack — useful in lightweight tooling.
    from src.utils.analysts import ANALYST_CONFIG
    return set(ANALYST_CONFIG.keys())


def _dedupe_preserving_order(names: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def resolve_analysts(
    template: str | None = None,
    custom: list[str] | None = None,
) -> list[str]:
    """Return the concrete analyst-key list for a pipeline run.

    Rules:
      * Exactly one of ``template`` or ``custom`` may be specified.
      * ``template`` looks up a name in ``TEMPLATES``; unknown name raises.
      * ``custom`` accepts any list of valid analyst keys; ``scanner_signal``
        is auto-prepended if the user forgot — it's the whole point of the
        bridge, accidentally omitting it would silently neuter the run.
      * Every resolved name must appear in ``ANALYST_CONFIG``; unknowns
        raise ``ValueError`` BEFORE the orchestrator invokes the workflow
        (cheap fail-fast vs LangGraph blowing up mid-run).
      * Result is deduped while preserving order.
    """
    if template is not None and custom is not None:
        raise ValueError(
            "resolve_analysts: pass either template OR custom, not both"
        )

    if custom is not None:
        if not custom:
            raise ValueError("custom analyst list cannot be empty")
        names = list(custom)
        if "scanner_signal" not in names:
            # Auto-prepend so callers can't accidentally bypass the bridge.
            names = ["scanner_signal"] + names
    else:
        name = template or DEFAULT_TEMPLATE
        if name not in TEMPLATES:
            raise ValueError(
                f"unknown template {name!r}; valid: {sorted(TEMPLATES)}"
            )
        names = list(TEMPLATES[name])

    resolved = _dedupe_preserving_order(names)
    valid = _known_analyst_keys()
    bad = [n for n in resolved if n not in valid]
    if bad:
        raise ValueError(
            f"unknown analyst key(s): {bad}; valid: {sorted(valid)}"
        )
    return resolved
