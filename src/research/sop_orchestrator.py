"""Analyze SOP orchestrated by LangGraph with explicit parallel joins.

Dispatches SECTION_ORDER, keeps exclusions explicit, shares persona
assignments with debate, and appends technical backtest results.
Section computations and chart rendering are retained.
"""

from __future__ import annotations

import logging
import os
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END
from datetime import date

from src.research.backtest_signal import run_signal_backtest
from src.research.charts.intraday_fetch import fetch_intraday_prices
from src.research.charts.render import (
    png_to_b64_uri,
    render_daily_kline_png,
    render_equity_curve_b64,
    render_intraday_png,
    render_weekly_kline_png,
    render_fundamental_trends_png,
    render_valuation_band_png,
    render_relative_strength_png,
)
from src.research.models import (
    AnalyzeReport,
    AnalyzeRequest,
    BacktestVerdict,
    SECTION_ORDER,
    SectionPayload,
)
from src.research.router import route_personas
from src.research.sections import SECTION_REGISTRY
from src.research.sections.base import SectionContext
from src.research.shared_data import fetch_shared_data

logger = logging.getLogger(__name__)

# Per the canvas redesign (2026-05-25), these sections are semantically
# independent — each consumes (shared, data_health) only (institutional_flow
# reads neither; it fetches dealer-gamma / short-volume by ticker). Dispatched
# concurrently via ThreadPoolExecutor; they're LLM- / IO-bound so threading
# buys near-linear speedup until the provider rate-limits.
_PARALLEL_SECTIONS = {
    "macro",
    "sector",
    "company_fundamentals",
    "financial_statements",
    "capital_structure",
    "ownership_structure",
    "valuation",
    "technical",
    "institutional_flow",
}

# Tunable via env so we can throttle if DeepSeek / OpenAI starts 429-ing.
_MAX_PARALLEL = int(os.environ.get("SOP_MAX_PARALLEL", "10"))

# Phase 10 Wave 2: intraday K-line is only useful for short-horizon
# objectives — see sop.md's "Technical Window Defaults" table. Maps the
# qualifying objective to its (yfinance period, interval). All other
# objectives skip the fetch entirely so the common report path isn't
# slowed by a network round-trip.
_INTRADAY_WINDOWS: dict[str, tuple[str, str]] = {
    "short_term": ("5d", "5m"),
    "earnings_review": ("1mo", "15m"),
}


def _persona_for(assignments: dict | None, section_name: str) -> str | None:
    if not assignments:
        return None
    value = assignments.get(section_name)
    return value if isinstance(value, str) else None


def _backtest_validation_md(b: BacktestVerdict, lang: str = "en") -> str:
    if lang == "zh":
        md = "\n\n### 回测验证\n\n" f"测试信号: **{b.signal}**  \n" f"窗口: {b.window_start} -> {b.window_end}  \n" f"事件次数: {b.n_signals}  \n"
        if b.win_rate_20d is not None and b.avg_return_20d is not None and b.t_stat is not None:
            md += f"胜率 (20日): {b.win_rate_20d * 100:.0f}%  \n" f"平均收益 (20日): {b.avg_return_20d * 100:+.2f}%  \n" f"t 统计量: {b.t_stat:.2f}  \n"
        md += f"\n**结论:** {b.verdict}\n"
        return md
    # English (default)
    md = "\n\n### Backtest Validation\n\n" f"Signal tested: **{b.signal}**  \n" f"Window: {b.window_start} -> {b.window_end}  \n" f"Occurrences: {b.n_signals}  \n"
    if b.win_rate_20d is not None and b.avg_return_20d is not None and b.t_stat is not None:
        md += f"Win rate (20d): {b.win_rate_20d * 100:.0f}%  \n" f"Avg return (20d): {b.avg_return_20d * 100:+.2f}%  \n" f"t-statistic: {b.t_stat:.2f}  \n"
    md += f"\n**Verdict:** {b.verdict}\n"
    return md


def _merge_sections(left, right):
    return {**left, **right}


class _AnalysisState(TypedDict):
    sections: Annotated[dict, _merge_sections]


def _run_sop(request: AnalyzeRequest, api_keys: dict | None = None, *, owner_id=None, force_rerun=False, source_scan_result_id=None, resume_run_id=None) -> AnalyzeReport:
    """End-to-end SOP runner. Returns AnalyzeReport with all sections,
    persona assignments (when use_personas), backtest verdict, and
    rendered_html=None (Task 16's render_sop populates that).

    Credentials stay in run-local closures and SectionContext, outside
    checkpoint state. Paid calls always require explicitly supplied keys.
    None never enables host environment key fallback."""
    from src.research.usage import CURRENT_USAGE
    usage = CURRENT_USAGE.get()
    scan_date = date.today().isoformat()
    from src.storage.analysis import AnalysisHistory
    from src.storage.checkpoint import OptionalMongoSaver
    provider = os.environ.get('RESEARCH_MODEL_PROVIDER', 'DeepSeek')
    model_route = {'credential_route': 'siliconflow' if provider.lower() == 'deepseek' and (api_keys or {}).get('SILICONFLOW_API_KEY') else provider.lower()}
    history = AnalysisHistory()
    checkpoint = None
    saver = OptionalMongoSaver()
    if resume_run_id:
        if force_rerun:
            raise ValueError('Resume and force rerun cannot be combined')
        ticket, shared = history.resume(owner_id=owner_id, request=request, run_id=resume_run_id, model_route=model_route)
        checkpoint = saver.get_tuple({'configurable': {'thread_id': ticket['run']['thread_id']}})
        if checkpoint is None and not ticket['cached']:
            raise ValueError('Checkpoint is unavailable')
    else:
        shared = fetch_shared_data(request.ticker, scan_date, market=request.market)
        ticket = history.start(owner_id=owner_id, request=request, shared=shared,
                               force=force_rerun, source_scan_result_id=source_scan_result_id, model_route=model_route)
    if ticket and ticket['cached']:
        cached = ticket['cached']
        return AnalyzeReport(request=request,
            sections={name: SectionPayload(**payload) for name, payload in cached['sections'].items()},
            persona_assignments=cached['sections'].get('_persona_assignments', {}).get('structured'),
            backtest=BacktestVerdict(**cached['backtest']) if cached.get('backtest') else None,
            rendered_html=None, reused=True, storage_status=history.store.status,
            mongo_report_id=str(cached['_id']), usage={'cache_hits': 1, 'calls': 0})

    # Router: only when persona-mode is on
    persona_assignments: dict | None = None
    if checkpoint:
        saved = checkpoint.checkpoint.get('channel_values', {}).get('sections', {}).get('_persona_assignments')
        persona_assignments = saved.structured if saved else None
    elif request.use_personas:
        try:
            # route_personas was built for ResearchRequest in Phase 2; adapt
            from src.research.models import ResearchRequest

            adapter = ResearchRequest(
                ticker=request.ticker,
                holding_status="watching",
                target_position_pct=0.05,
                risk_tolerance=request.risk_tolerance,
                report_goal="general_research",
                use_personas=True,
                scanner_context=None,
            )
            persona_assignments = route_personas(adapter, shared, api_keys=api_keys)
        except Exception as e:
            logger.exception("router failed: %s", e)
            persona_assignments = None

    # Technical-signal backtest runs once; attached to Technical section
    backtest: BacktestVerdict | None = None
    try:
        backtest = run_signal_backtest(shared, signal="auto")
    except Exception as e:
        logger.exception("backtest failed: %s", e)
        backtest = None

    # Stash persona assignments under a magic key so DebateSection sees them
    sections: dict[str, SectionPayload] = {}
    if persona_assignments is not None:
        sections["_persona_assignments"] = SectionPayload(
            name="_persona_assignments",
            markdown="",
            structured=persona_assignments,
            skipped=False,
            persona_used=None,
        )

    def _make_excluded(name: str) -> SectionPayload:
        return SectionPayload(
            name=name,
            markdown=f"## {name}\n\n_n/a -- user excluded_\n",
            structured=None,
            skipped=True,
            persona_used=None,
            skip_reason="user excluded this section",
        )

    def _make_unregistered(name: str) -> SectionPayload:
        return SectionPayload(
            name=name,
            markdown=f"## {name}\n\n_section not yet implemented_\n",
            structured=None,
            skipped=True,
            persona_used=None,
            skip_reason="no runner registered",
        )

    def _persona_for_request(name: str) -> str | None:
        p = _persona_for(persona_assignments, name)
        overrides = getattr(request, "persona_overrides", None)
        if overrides and name in overrides:
            p = overrides[name]
        return p

    def _run_one(name: str, prior_snapshot: dict[str, SectionPayload]) -> SectionPayload:
        runner = SECTION_REGISTRY.get(name)
        if runner is None:
            return _make_unregistered(name)
        ctx = SectionContext(
            request=request,
            shared=shared,
            persona=_persona_for_request(name),
            prior=prior_snapshot,
            api_keys=api_keys,
        )
        from src.research.usage import FAILED_CALLS
        failure_token = FAILED_CALLS.set(0)
        try:
            cached = None if force_rerun else history.section_get(ticket, name, prior_snapshot)
            if cached:
                usage.add(cache_hits=1)
                return SectionPayload(**cached['output'])
            result = runner.run(ctx)
            if FAILED_CALLS.get():
                from dataclasses import replace
                result = replace(result, skipped=True, skip_reason="Model request failed; output unavailable")
            history.section_put(ticket, name, prior_snapshot, result)
            return result
        except Exception as e:
            logger.exception("section %s raised: %s", name, e)
            return SectionPayload(
                name=name,
                markdown=f"## {name}\n\n_unavailable: {e}_\n",
                structured=None,
                skipped=True,
                persona_used=None,
                skip_reason=f"unhandled exception: {e}",
            )
        finally:
            FAILED_CALLS.reset(failure_token)

    graph = StateGraph(_AnalysisState)
    def section_node(name):
        def node(state):
            payload = _make_excluded(name) if name not in request.included_sections else _run_one(name, dict(state['sections']))
            return {'sections': {name: payload}}
        return node

    previous = START
    pending = []
    for name in ['data_health', *[n for n in SECTION_ORDER if n in _PARALLEL_SECTIONS],
                 'scenarios', 'risk_position', 'conviction', 'event_risk', 'catalyst', 'debate',
                 'final_strategy', 'evidence_ledger', 'executive_summary', 'missing_data']:
        graph.add_node(name, section_node(name))
        if name in _PARALLEL_SECTIONS:
            graph.add_edge(previous, name)
            pending.append(name)
            continue
        if pending:
            graph.add_edge(pending, name)  # explicit join: wait for every branch
            pending = []
        else:
            graph.add_edge(previous, name)
        previous = name
    if pending:
        graph.add_edge(pending, END)
    else:
        graph.add_edge(previous, END)
    from src.storage.checkpoint import OptionalMongoSaver
    from uuid import uuid4
    thread_id = ticket['run']['thread_id'] if ticket else f'{owner_id or "ephemeral"}:{uuid4().hex}'
    try:
        result = graph.compile(checkpointer=saver).invoke(None if checkpoint else {'sections': sections},
            config={'max_concurrency': max(1, _MAX_PARALLEL), 'configurable': {'thread_id': thread_id}})
    except Exception as error:
        history.save(ticket, None, error=error)
        raise
    sections = result['sections']

    # Append Backtest Validation to Technical's markdown + embed equity-curve PNG
    if backtest is not None and "technical" in sections and not sections["technical"].skipped:
        tech = sections["technical"]

        # Generate inline equity-curve b64 for email/web consumption.
        # Pulled from shared.prices closes + backtest.signal_indices (which
        # the Phase 5A backtest now exposes). On any failure (e.g. matplotlib
        # not installed, empty prices), structured stays None and the
        # rendered HTML simply omits the inline image — the K-line endpoint
        # will still serve PNGs on demand.
        # Phase 10: render 3 inline charts (daily K + weekly K + equity
        # curve). Each is best-effort — any failure logs but doesn't abort.
        chart_b64: str | None = None
        chart_daily_b64: str | None = None
        chart_weekly_b64: str | None = None
        try:
            from src.research.backtest_signal import _closes

            closes = _closes(shared)
            idx = backtest.signal_indices or []
            chart_b64 = render_equity_curve_b64(closes, idx, horizon=20)
        except Exception as e:
            logger.exception("equity-curve chart render failed: %s", e)

        prices = getattr(shared, "prices", None) or []
        if prices:
            try:
                chart_daily_b64 = png_to_b64_uri(render_daily_kline_png(prices, title=f"{request.ticker} Daily"))
            except Exception as e:
                logger.exception("daily K-line render failed: %s", e)
            try:
                chart_weekly_b64 = png_to_b64_uri(render_weekly_kline_png(prices, title=f"{request.ticker} Weekly"))
            except Exception as e:
                logger.exception("weekly K-line render failed: %s", e)

        # Phase 10 Wave 2: intraday 5-min K-line, only for short-horizon
        # objectives (short_term / earnings_review). Intraday bars aren't in
        # shared.prices, so fetch on demand from yfinance — best-effort, so
        # a non-US / older ticker simply yields an empty list → no chart.
        chart_intraday_b64: str | None = None
        intraday_window = _INTRADAY_WINDOWS.get(request.objective)
        if intraday_window:
            period, interval = intraday_window
            try:
                intraday_prices = fetch_intraday_prices(request.ticker, period=period, interval=interval)
                if intraday_prices:
                    chart_intraday_b64 = png_to_b64_uri(render_intraday_png(intraday_prices, title=f"{request.ticker} Intraday"))
            except Exception as e:
                logger.exception("intraday K-line render failed: %s", e)

        new_structured: dict | None
        if isinstance(tech.structured, dict):
            new_structured = dict(tech.structured)
        elif tech.structured is None:
            new_structured = {} if (chart_b64 or chart_daily_b64 or chart_weekly_b64 or chart_intraday_b64) else None
        else:
            new_structured = tech.structured  # keep non-dict structured as-is
        if isinstance(new_structured, dict):
            if chart_b64:
                new_structured["chart_equity_curve_b64"] = chart_b64
            if chart_daily_b64:
                new_structured["chart_kline_daily_b64"] = chart_daily_b64
            if chart_weekly_b64:
                new_structured["chart_kline_weekly_b64"] = chart_weekly_b64
            if chart_intraday_b64:
                new_structured["chart_kline_intraday_b64"] = chart_intraday_b64

        sections["technical"] = SectionPayload(
            name="technical",
            markdown=tech.markdown + _backtest_validation_md(backtest, request.report_language),
            structured=new_structured,
            skipped=False,
            persona_used=tech.persona_used,
        )

    # ---- inline charts for non-technical sections (best-effort) ----------
    # Embedded via html_render._section_chart_imgs (structured["charts"]).
    # Guarded on data sufficiency so we never emit a "No data" placeholder.
    def _attach_chart(section_name: str, render_fn, *, alt: str, caption: str) -> None:
        payload = sections.get(section_name)
        if payload is None or payload.skipped:
            return
        try:
            src = png_to_b64_uri(render_fn())
        except Exception as e:
            logger.exception("section chart %s failed: %s", section_name, e)
            return
        structured = dict(payload.structured) if isinstance(payload.structured, dict) else {}
        structured["charts"] = list(structured.get("charts") or []) + [{"src": src, "alt": alt, "caption": caption}]
        sections[section_name] = SectionPayload(
            name=payload.name,
            markdown=payload.markdown,
            structured=structured,
            skipped=payload.skipped,
            persona_used=payload.persona_used,
        )

    _fins = getattr(shared, "financials", None) or []
    # P/E "current" marker from the live snapshot, captured before we possibly
    # swap _fins for multi-period yfinance history (the hybrid provider returns
    # only 1 fundamentals period, so trend/band charts need a history source).
    _cur_pe = getattr(_fins[0], "price_to_earnings_ratio", None) if _fins else None
    if len(_fins) >= 2:
        _attach_chart(
            "financial_statements",
            lambda: render_fundamental_trends_png(_fins, title=f"{request.ticker} Margins & Growth"),
            alt="Fundamental trends",
            caption="Gross / operating / net margin + revenue growth over reported periods.",
        )
        _attach_chart(
            "valuation",
            lambda: render_valuation_band_png(
                _fins,
                current_value=_cur_pe,
                metric="price_to_earnings_ratio",
                title=f"{request.ticker} Valuation Band (P/E)",
            ),
            alt="Valuation band",
            caption="P/E over reported periods with historical min-max band; latest value marked.",
        )
    _prices = getattr(shared, "prices", None) or []
    _sector_px = getattr(shared, "sector_etf_prices", None) or []
    if len(_prices) >= 2 and len(_sector_px) >= 2:
        _attach_chart(
            "sector",
            lambda: render_relative_strength_png(
                _prices,
                _sector_px,
                ticker_label=request.ticker,
                benchmark_label="Sector ETF",
                title=f"{request.ticker} vs Sector ETF",
            ),
            alt="Relative strength",
            caption="Price vs sector ETF, both rebased to 100 at window start.",
        )

    report = AnalyzeReport(
        request=request,
        sections=sections,
        persona_assignments=persona_assignments,
        backtest=backtest,
        rendered_html=None,
    )
    report['analysis_run_id'] = str(ticket['run']['_id']) if ticket else None
    report['analysis_status'] = 'partial' if any(p.skipped and p.skip_reason != 'user excluded this section' for n,p in sections.items() if not n.startswith('_')) else 'succeeded'
    report['usage'] = usage.snapshot()
    report['mongo_report_id'] = history.save(ticket, report)
    report['storage_status'] = history.store.status
    return report


def run_sop(request: AnalyzeRequest, api_keys: dict | None = None, *, owner_id=None,
            force_rerun=False, source_scan_result_id=None, resume_run_id=None) -> AnalyzeReport:
    from src.research.usage import CURRENT_USAGE, Usage
    token = CURRENT_USAGE.set(Usage())
    try:
        return _run_sop(request, api_keys, owner_id=owner_id, force_rerun=force_rerun,
                        source_scan_result_id=source_scan_result_id, resume_run_id=resume_run_id)
    finally:
        CURRENT_USAGE.reset(token)
