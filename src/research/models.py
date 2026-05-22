"""Dataclass models for the research pipeline.

All types here are pure data — no I/O, no business logic. They define
the contract between modules, the synthesizer, the backtest, and the
LangGraph state. Phase 1 keeps these stable; Phase 2 adds persona
plumbing without changing the shapes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypedDict


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
