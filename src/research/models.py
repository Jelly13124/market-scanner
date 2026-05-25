"""Dataclass models for the research pipeline.

All types here are pure data — no I/O, no business logic. They define
the contract between modules, the synthesizer, the backtest, and the
LangGraph state. Phase 1 keeps these stable; Phase 2 adds persona
plumbing without changing the shapes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict


HoldingStatus = Literal["holding", "watching", "considering_buy", "considering_short"]
RiskTolerance = Literal["conservative", "moderate", "aggressive"]
ReportGoal = Literal["new_entry", "hold_review", "exit_decision", "general_research"]
Direction = Literal["long", "short", "stand_aside"]
SampleQuality = Literal["strong", "moderate", "weak", "insufficient"]


@dataclass
class ResearchRequest:
    """Inputs to a single per-ticker research run.

    ``holding_status``, ``target_position_pct``, ``risk_tolerance`` and
    ``report_goal`` shape what the synthesizer writes. ``use_personas``
    is a no-op in Phase 1 (no router yet) but persisted so Phase 2 can
    pick it up. ``scanner_context`` is populated by the cron path and
    omitted for on-demand calls.
    """

    ticker: str
    holding_status: HoldingStatus
    target_position_pct: float
    risk_tolerance: RiskTolerance
    report_goal: ReportGoal
    use_personas: bool
    scanner_context: dict | None = None


@dataclass
class ModuleResult:
    """One analytical module's output.

    ``markdown`` is the human-readable section content that the synthesizer
    will reference. ``key_metrics`` is a numeric extract that the
    synthesizer can quote without re-parsing markdown. ``skipped=True``
    means the module ran cleanly but couldn't produce useful output
    (e.g., no news data) — the pipeline carries on; the section is
    omitted from the final report.
    """

    module_name: str
    persona_used: str | None
    markdown: str
    key_metrics: dict[str, float] = field(default_factory=dict)
    chart_data: dict | None = None
    skipped: bool = False
    skip_reason: str | None = None


@dataclass
class TradePlan:
    """Single-shot trade plan emitted by the synthesizer.

    ``direction="stand_aside"`` is the explicit no-trade signal; in that
    case ``entry_price``/``target_price``/``stop_price`` are all None and
    ``horizon_days``/``sizing_pct`` are 0. Synthesizer uses stand_aside
    when the bear case dominates, the user is not already holding, and
    no high-confidence long setup exists.
    """

    direction: Direction
    entry_price: float | None
    target_price: float | None
    stop_price: float | None
    horizon_days: int
    sizing_pct: float
    confidence: int  # 0-100
    rationale: str


@dataclass
class BacktestSummary:
    """Output of the detector-replay backtest.

    Replays the synthesizer's TradePlan over past dates on this ticker
    where the same detector trigger set fired. Sample size quality is
    bucketed so the consumer (HTML report / synthesizer prompt) can
    surface a caveat for small-n cases.
    """

    matches_found: int
    win_rate: float | None
    avg_pnl_pct: float | None
    max_drawdown_pct: float | None
    avg_holding_days: float | None
    sample_quality: SampleQuality
    caveat: str | None = None


class ResearchState(TypedDict, total=False):
    """LangGraph state carried through the pipeline.

    ``total=False`` so intermediate nodes can populate fields incrementally
    without TypedDict yelling about missing keys.
    """

    request: ResearchRequest
    persona_assignments: dict[str, str | list[str] | None] | None
    module_results: dict[str, ModuleResult]
    report_markdown: str | None
    strategy: TradePlan | None
    backtest_summary: BacktestSummary | None
    rendered_html: str | None


# ===========================================================================
# Phase 4 - SOP-driven analyze pipeline
# ===========================================================================

Objective = Literal[
    "target_price", "short_term", "medium_term", "long_term",
    "earnings_review", "general_research",
]
RiskBand = Literal["conservative", "balanced", "aggressive"]


# Canonical SOP section order. Section runners are dispatched in this
# order so that downstream sections can read upstream payloads (e.g.
# Executive Summary reads Evidence Ledger; Scenarios reads Valuation).
SECTION_ORDER: list[str] = [
    "data_health",
    "executive_summary",
    "evidence_ledger",
    "macro",
    "sector",
    "company_fundamentals",
    "financial_statements",
    "valuation",
    "technical",
    "risk_position",
    "scenarios",
    "conviction",
    "event_risk",
    "debate",
    "final_strategy",
    "missing_data",
]


@dataclass
class AnalyzeRequest:
    """User-supplied parameters for a full SOP run.

    Mirrors the skill's combined-question gate. ``included_sections``
    drives the flow-style module picker; sections not listed are
    rendered as 'n/a -- user excluded'.

    ``persona_overrides`` (Phase 5D) pins specific personas per section,
    bypassing the router. Sections absent from the dict fall through to
    the router (when ``use_personas`` is on) or objective mode (when
    off). ``None`` means "no overrides at all" — Phase 4 behavior.

    ``debate_rounds`` (Phase 5E) controls how many back-and-forth rounds
    the Debate section's single LLM call simulates. Clamped to 1..5;
    default 3. Only consumed by Debate section when ``use_personas=True``.
    Kept at the END of the dataclass so existing positional-construction
    call sites keep working.
    """
    ticker: str
    objective: Objective
    position_budget_usd: float | None
    already_holds: bool
    cost_basis_usd: float | None
    risk_tolerance: RiskBand
    use_personas: bool
    included_sections: set[str] = field(default_factory=lambda: set(SECTION_ORDER))
    persona_overrides: dict[str, str] | None = None
    debate_rounds: int = 3

    def __post_init__(self) -> None:
        # Clamp to a sane window — guards against the API schema being
        # bypassed (direct dataclass construction from tests / CLI).
        if not isinstance(self.debate_rounds, int):
            self.debate_rounds = 3
        self.debate_rounds = max(1, min(5, self.debate_rounds))


@dataclass
class SectionPayload:
    """One SOP section's output. ``structured`` is section-specific
    (e.g. Evidence Ledger emits a list[dict]; Scenarios emits a dict
    with bear/base/bull; most prose sections leave it None)."""
    name: str
    markdown: str
    structured: Any | None
    skipped: bool
    persona_used: str | None
    skip_reason: str | None = None


@dataclass
class BacktestVerdict:
    """Output of the technical-signal backtest, embedded inside the
    Technical Analysis section under 'Backtest Validation'.

    ``signal_indices`` is optional/backwards-compatible: Phase 5A added
    it so the chart pipeline can re-derive the equity curve without
    re-running the per-signal detector. None for legacy/test paths that
    don't populate it.
    """
    signal: str
    window_start: str
    window_end: str
    n_signals: int
    win_rate_20d: float | None
    avg_return_20d: float | None
    t_stat: float | None
    significant: bool
    verdict: str
    signal_indices: list[int] | None = None


class AnalyzeReport(TypedDict, total=False):
    """End-to-end output of sop_orchestrator.run_sop."""
    request: AnalyzeRequest
    sections: dict[str, SectionPayload]
    persona_assignments: dict | None
    backtest: BacktestVerdict | None
    rendered_html: str | None
