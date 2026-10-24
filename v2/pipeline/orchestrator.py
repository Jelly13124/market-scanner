"""Pipeline orchestrator — composes ``run_scan`` and ``run_hedge_fund``.

Single entry point ``run_pipeline(...)`` shared by the FastAPI route
(interactive UI button) and the daily scheduler job. Sequence:

  1. Resolve scan_date (default = latest trading day ≤ today).
  2. Resolve analyst list (template or custom, validated).
  3. Load universe tickers.
  4. Run the v2 scanner → ScoredEntry[].
  5. Translate top-N entries into ``scanner_context``.
  6. Run the LangGraph agent workflow with the scanner context injected.
  7. Wrap into a ``PipelineResult`` (Phase 3 will persist to DB).
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable

from v2.data.protocol import DataClient
from v2.pipeline.templates import resolve_analysts
from v2.scanner.models import ScoredEntry

logger = logging.getLogger(__name__)


# Default portfolio shape — minimum keys run_hedge_fund + downstream
# risk_management / portfolio_manager expect. UI callers should usually
# pass their own portfolio; daily cron uses this default.
_DEFAULT_PORTFOLIO: dict[str, Any] = {
    "cash": 100_000.0,
    "margin_requirement": 0.0,
    "margin_used": 0.0,
    "positions": {},
    "realized_gains": {},
}


@dataclass
class PipelineResult:
    """End-to-end run output. Shape mirrors what Phase 3 persists to the DB."""

    run_id: str
    scan_date: str
    template: str  # "<template-name>" or "custom"
    selected_analysts: list[str]
    universe: str
    top_n: int
    watchlist: list[dict] = field(default_factory=list)        # ScoredEntry.model_dump()
    agent_decisions: dict[str, Any] = field(default_factory=dict)
    analyst_signals: dict[str, dict[str, dict]] = field(default_factory=dict)
    duration_seconds: float = 0.0
    status: str = "complete"                                    # complete | error
    error: str | None = None


def _entry_to_scanner_context(entry: ScoredEntry, scan_date: str) -> dict[str, Any]:
    """Transform one ``ScoredEntry`` into the per-ticker ``scanner_context``
    shape consumed by ``scanner_signal_agent``.

    Drops un-triggered trigger entries (they only have triggered=False rows
    when the detector ran cleanly but didn't fire — irrelevant to the LLM
    summary). Per-detector ``components`` dicts are passed through verbatim.
    """
    triggered = [t for t in (entry.triggers or []) if isinstance(t, dict) and t.get("triggered")]
    triggered_names = [t["detector"] for t in triggered if t.get("detector")]
    triggered_components = {
        t["detector"]: t.get("components", {}) or {}
        for t in triggered
        if t.get("detector")
    }
    return {
        "scan_date": scan_date,
        "rank": entry.rank,
        "composite_score": entry.composite_score,
        "direction": entry.direction,
        "event_severity": entry.event_severity,
        "triggered_detectors": triggered_names,
        "triggered_components": triggered_components,
    }


def _resolve_default_scan_date(
    provider_factory: Callable[[], DataClient] | None = None,
) -> str:
    """Return the most recent trading day on/before today (ISO YYYY-MM-DD).

    Uses ``trading_days_between`` over a 14-day backward window which is
    safe across long weekends + holidays. Falls back to "today as weekday"
    if the provider fails — better to attempt a scan that yields no data
    than to crash the orchestrator before it does anything.
    """
    from v2.backtesting.trading_calendar import trading_days_between
    from v2.data.factory import get_provider_factory

    today = date.today()
    start = (today - timedelta(days=14)).isoformat()
    end = today.isoformat()
    factory = provider_factory or get_provider_factory()
    try:
        client = factory()
        try:
            days = trading_days_between(client, start_date=start, end_date=end)
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
    except Exception as e:
        logger.warning("Failed to resolve trading calendar (%s); falling back", e)
        days = []

    if days:
        return days[-1]
    # Fall back to today (or last weekday) — scan will probably 0-row but
    # caller gets a clean error rather than a TypeError here.
    d = today
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


def run_pipeline(
    *,
    scan_date: str | None = None,
    universe: str = "nasdaq100",
    universe_tickers: list[str] | None = None,
    top_n: int = 5,
    template: str | None = None,
    custom_analysts: list[str] | None = None,
    portfolio: dict | None = None,
    model_name: str = "gpt-4.1",
    model_provider: str = "OpenAI",
    show_reasoning: bool = False,
    persist: bool = True,
    use_quant_signals: bool = True,
    # Injection points for tests (avoid heavy imports at module load).
    run_scan_fn: Callable | None = None,
    run_hedge_fund_fn: Callable | None = None,
    provider_factory: Callable[[], DataClient] | None = None,
) -> PipelineResult:
    """Run scanner → agents end-to-end and return a ``PipelineResult``.

    Args:
      scan_date:        Default = latest trading day ≤ today.
      universe:         Scanner universe kind (``nasdaq100``, ``sp500``,
                        ``custom`` requires ``universe_tickers``).
      top_n:            Watchlist size handed to agents.
      template:         Named analyst roster (see ``TEMPLATES``).
                        Mutually exclusive with ``custom_analysts``.
      custom_analysts:  Explicit analyst-key list; bypasses templates.
                        ``scanner_signal`` is auto-prepended if missing.
      portfolio:        Initial portfolio dict; defaults to a $100k cash
                        long-only setup.
      persist:          v1: no-op (DB persistence lands in Phase 3).
      run_scan_fn,
      run_hedge_fund_fn,
      provider_factory: Test injection seams — production callers leave
                        these at None.

    Raises:
      ValueError on bad template / unknown analyst keys (validated upfront
      so we don't waste a scan on a doomed workflow call).
    """
    t0 = time.monotonic()
    run_id = uuid.uuid4().hex
    chosen_template = template if (template is not None or custom_analysts is None) else "custom"
    if template is None and custom_analysts is None:
        # Make the default explicit in the result so persistence sees a
        # concrete name rather than None.
        from v2.pipeline.templates import DEFAULT_TEMPLATE
        chosen_template = DEFAULT_TEMPLATE

    # 1. Validate analysts BEFORE running a scan (fail-fast).
    selected = resolve_analysts(template=template, custom=custom_analysts)

    # 2. Resolve scan_date.
    if scan_date is None:
        scan_date = _resolve_default_scan_date(provider_factory)

    # 3. Resolve universe → ticker list.
    from v2.scanner.universes.loader import load_universe
    if universe == "custom":
        tickers = load_universe("custom", custom=universe_tickers)
    else:
        tickers = load_universe(universe)

    # 4. Run the scan with the full quant signal suite enabled.
    #    Before 2026-05-19 this call omitted ``quant_signals`` entirely, so
    #    composite_score = event_score only (quant_weight=0.40 → effectively
    #    wasted). Wiring the 5 default signals lets the scoring formula
    #    actually use the 60/40 event/quant split it was designed for.
    if run_scan_fn is None:
        from v2.scanner.runner import run_scan as run_scan_fn  # type: ignore[no-redef]
    from v2.signals import ALL_SIGNALS

    quant_instances = [cls() for cls in ALL_SIGNALS] if use_quant_signals else None
    logger.info(
        "pipeline %s: scanning %d tickers as of %s (universe=%s, top_n=%d, "
        "quant_signals=%d)",
        run_id, len(tickers), scan_date, universe, top_n,
        len(quant_instances) if quant_instances else 0,
    )
    scored: list[ScoredEntry] = run_scan_fn(
        tickers=tickers,
        end_date=scan_date,
        top_n=top_n,
        provider_factory=provider_factory,
        quant_signals=quant_instances,
    )

    if not scored:
        # Scanner returned no entries — return a clean result rather than
        # invoking the workflow on an empty list (LangGraph might handle
        # it, but it's wasted LLM calls).
        return PipelineResult(
            run_id=run_id,
            scan_date=scan_date,
            template=chosen_template,
            selected_analysts=selected,
            universe=universe,
            top_n=top_n,
            watchlist=[],
            agent_decisions={},
            analyst_signals={},
            duration_seconds=time.monotonic() - t0,
            status="complete",
        )

    # 5. Translate to scanner_context (per-ticker dict).
    scanner_context = {
        entry.ticker: _entry_to_scanner_context(entry, scan_date)
        for entry in scored
    }
    top_tickers = [e.ticker for e in scored]

    # 6. Run the agent workflow.
    if run_hedge_fund_fn is None:
        from src.main import run_hedge_fund as run_hedge_fund_fn  # type: ignore[no-redef]

    # start_date gives agents ~250 calendar days (~180 trading days) of
    # history. technical_analyst's momentum_6m uses returns.rolling(126).sum()
    # and the volatility regime uses a 63-day rolling window; 90 days only
    # gives ~63 trading days so both come back NaN→0 for every ticker.
    start_d = (datetime.strptime(scan_date, "%Y-%m-%d").date()
               - timedelta(days=250)).isoformat()
    logger.info(
        "pipeline %s: invoking workflow on %d tickers with %d analysts",
        run_id, len(top_tickers), len(selected),
    )
    # Note: macro context used to be precomputed here and injected into
    # persona prompts. It's now a proper analyst agent (macro_agent) that
    # is added to the balanced template and emits a normal signal — see
    # src/agents/macro_agent.py. Nothing to precompute at the orchestrator
    # level any more; the agent handles its own caching.

    fund_result = run_hedge_fund_fn(
        tickers=top_tickers,
        start_date=start_d,
        end_date=scan_date,
        portfolio=portfolio or dict(_DEFAULT_PORTFOLIO),
        show_reasoning=show_reasoning,
        selected_analysts=selected,
        model_name=model_name,
        model_provider=model_provider,
        scanner_context=scanner_context,
    )

    # 7. Wrap. fund_result has 'decisions' + 'analyst_signals'.
    result = PipelineResult(
        run_id=run_id,
        scan_date=scan_date,
        template=chosen_template,
        selected_analysts=selected,
        universe=universe,
        top_n=top_n,
        watchlist=[e.model_dump() for e in scored],
        agent_decisions=fund_result.get("decisions") or {},
        analyst_signals=fund_result.get("analyst_signals") or {},
        duration_seconds=time.monotonic() - t0,
        status="complete",
    )

    return result


def run_agents_only(
    *,
    tickers: list[str],
    scan_date: str,
    scanner_context: dict[str, Any] | None = None,
    template: str | None = None,
    custom_analysts: list[str] | None = None,
    portfolio: dict | None = None,
    model_name: str = "gpt-4.1",
    model_provider: str = "OpenAI",
    show_reasoning: bool = False,
    run_hedge_fund_fn: Callable | None = None,
) -> dict[str, Any]:
    """Run the agent workflow on a caller-provided ticker list, skipping the scan.

    Used for A/B backtests where group B feeds randomly-sampled tickers
    through the same agent pipeline (with empty ``scanner_context``) so we
    can compare PM decision quality on scanner-flagged vs random tickers.

    Returns ``{'decisions': ..., 'analyst_signals': ..., 'duration_seconds': ...,
    'selected_analysts': ...}``. The shape mirrors what ``run_pipeline``
    extracts from ``run_hedge_fund`` so callers can reuse the same
    downstream tooling.
    """
    t0 = time.monotonic()
    selected = resolve_analysts(template=template, custom=custom_analysts)

    if run_hedge_fund_fn is None:
        from src.main import run_hedge_fund as run_hedge_fund_fn  # type: ignore[no-redef]

    start_d = (datetime.strptime(scan_date, "%Y-%m-%d").date()
               - timedelta(days=250)).isoformat()
    fund_result = run_hedge_fund_fn(
        tickers=tickers,
        start_date=start_d,
        end_date=scan_date,
        portfolio=portfolio or dict(_DEFAULT_PORTFOLIO),
        show_reasoning=show_reasoning,
        selected_analysts=selected,
        model_name=model_name,
        model_provider=model_provider,
        scanner_context=scanner_context or {},
    )
    return {
        "decisions": fund_result.get("decisions") or {},
        "analyst_signals": fund_result.get("analyst_signals") or {},
        "selected_analysts": selected,
        "duration_seconds": time.monotonic() - t0,
    }


