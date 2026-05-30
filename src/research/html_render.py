"""Phase 4 HTML rendering for AnalyzeReport.

The skill's vendored template has scalar-only Jinja placeholders.
``render_sop`` is a two-phase pass:
  1. Jinja fills the 22 scalar placeholders, producing a "skeleton" HTML
     with empty section bodies (the template's <h2> blocks have empty
     <tbody>/<ul>/<p> slots designed to be filled post-render).
  2. Python string-injects each section's markdown-converted HTML body
     under its <h2> heading.

The Phase 3 ``render_html(state)`` API is still used by Phase 3
endpoints (app/backend/routes/research.py + scheduler_service.py).
It is kept intact until Phase 4 Task 19 swaps callers over to
``render_sop``.
"""

from __future__ import annotations

import html as _html
import re
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.research.models import AnalyzeReport, ResearchState


_TEMPLATE_DIR = Path(__file__).parent / "templates"
_ENV = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


# ---------------------------------------------------------------------------
# Shared markdown converter
# ---------------------------------------------------------------------------

def _inline(s: str) -> str:
    """Apply inline markdown (bold, italic, code)."""
    # Order matters: bold (**) before italic (*) so ** isn't consumed by *.
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![*\w])\*([^*\n]+?)\*(?!\w)", r"<em>\1</em>", s)
    s = re.sub(r"`([^`]+?)`", r"<code>\1</code>", s)
    return s


def _markdown_to_html(text: str, *, skip_h2: bool = False) -> str:
    """Minimal markdown subset -> HTML.

    Handles: ## / ### headings, bold (**), italic (*), inline code (`...`),
    bullet lists (- / *), simple GitHub-style tables, paragraphs.

    ``skip_h2``: when True, drop level-2 headings entirely. The Phase 4
    template already provides the H2 for each section; re-emitting one
    inside the injected body would duplicate the heading.
    """
    if not text:
        return ""

    lines = text.split("\n")
    out: list[str] = []
    i = 0
    in_list = False
    in_table = False

    while i < len(lines):
        raw = lines[i].rstrip()
        stripped = raw.strip()

        if not stripped:
            if in_list:
                out.append("</ul>")
                in_list = False
            if in_table:
                out.append("</tbody></table>")
                in_table = False
            out.append("")
            i += 1
            continue

        # Markdown table: header row + separator row (---|---) + body rows
        if (
            "|" in raw
            and i + 1 < len(lines)
            and re.match(r"^\s*\|?\s*[-:|\s]+\|?\s*$", lines[i + 1])
        ):
            if in_list:
                out.append("</ul>")
                in_list = False
            headers = [c.strip() for c in raw.strip("|").split("|")]
            out.append(
                "<table><thead><tr>"
                + "".join(
                    f"<th>{_inline(_html.escape(h))}</th>" for h in headers
                )
                + "</tr></thead><tbody>"
            )
            i += 2  # skip header + separator
            in_table = True
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                out.append(
                    "<tr>"
                    + "".join(
                        f"<td>{_inline(_html.escape(c))}</td>" for c in cells
                    )
                    + "</tr>"
                )
                i += 1
            out.append("</tbody></table>")
            in_table = False
            continue

        # Headings (## ###)
        m = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if m:
            if in_list:
                out.append("</ul>")
                in_list = False
            level = len(m.group(1))
            content = _inline(_html.escape(m.group(2)))
            if skip_h2 and level == 2:
                i += 1
                continue
            # Cap at h4 so we don't emit nonsense levels
            level = min(level, 4)
            out.append(f"<h{level + 2 if not skip_h2 else level}>"
                       f"{content}</h{level + 2 if not skip_h2 else level}>")
            i += 1
            continue

        # Bullet list item
        if stripped.startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul>")
                in_list = True
            item = stripped[2:]
            out.append(f"<li>{_inline(_html.escape(item))}</li>")
            i += 1
            continue

        # Paragraph
        if in_list:
            out.append("</ul>")
            in_list = False
        out.append(f"<p>{_inline(_html.escape(raw))}</p>")
        i += 1

    if in_list:
        out.append("</ul>")
    if in_table:
        out.append("</tbody></table>")
    return "\n".join(out)


# ===========================================================================
# Phase 4: render_sop(AnalyzeReport) -> HTML
# ===========================================================================

# Map section name -> the H2 heading text in the upstream template.
# This dict is the contract between SECTION_ORDER and the vendored
# template. If the template's H2 text changes, update here. Sections
# that have no <h2> in the template (e.g. evidence_ledger, debate,
# missing_data — these live inside <details> blocks in the skeleton)
# get appended at end of <main>.
_HEADING_MAP = {
    "data_health":          "Data Health",
    "executive_summary":    "Executive Summary",
    "macro":                "Macro Regime",
    "sector":               "Sector and Peer Comparison",
    "company_fundamentals": "Company Fundamentals",
    "financial_statements": "Financial Statement Review",
    "valuation":            "Valuation Analysis",
    "technical":            "Technical Analysis",
    "risk_position":        "Risk and Position Sizing",
    "scenarios":            "Bear / Base / Bull Scenarios",
    "conviction":           "Conviction / Setup Quality Score",
    "event_risk":           "Event Risk Check",
    "final_strategy":       "Final Conditional Strategy",
}

# Sections that the template renders inside <details> blocks rather
# than <h2> sections. Append at end of <main> with a synthetic <h2>
# so the user sees them.
_APPENDIX_SECTIONS = {
    "evidence_ledger": "Evidence Ledger",
    "debate":          "Debate Summary",
    "missing_data":    "Missing Data / Low Confidence",
}

# Phase 11.1 fix: the report.html template itself ships English <h2> tags
# (e.g. '<h2>Executive Summary</h2>'). When request.report_language=='zh'
# we do a final pass over the rendered HTML and swap each template H2 to
# its Chinese equivalent — otherwise the body would be Chinese but the
# heading above it would stay English.
_HEADING_ZH_MAP = {
    "Data Health":                          "数据健康度",
    "Executive Summary":                    "执行摘要",
    "Macro Regime":                         "宏观环境",
    "Sector and Peer Comparison":           "行业与同业比较",
    "Company Fundamentals":                 "公司基本面",
    "Financial Statement Review":           "财务报表回顾",
    "Valuation Analysis":                   "估值分析",
    "Technical Analysis":                   "技术分析",
    "Risk and Position Sizing":             "风险与仓位管理",
    "Bear / Base / Bull Scenarios":         "熊 / 基准 / 牛 情景",
    "Conviction / Setup Quality Score":     "信念 / 配置质量评分",
    "Event Risk Check":                     "事件风险检查",
    "Final Conditional Strategy":           "最终条件性策略",
    "Evidence Ledger":                      "证据账本",
    "Debate Summary":                       "辩论纪要",
    "Missing Data / Low Confidence":        "缺失数据 / 低置信领域",
}


def _localize_template_headings(html: str, lang: str) -> str:
    """Phase 11.1: when lang=='zh', rewrite every English <h2>X</h2> in the
    rendered HTML to its Chinese equivalent so headings match body."""
    if lang != "zh":
        return html
    for en, zh in _HEADING_ZH_MAP.items():
        # Match the exact <h2>EN</h2> form — the template doesn't use
        # attributes on these h2 tags, so a literal replace is safe.
        html = html.replace(f"<h2>{en}</h2>", f"<h2>{zh}</h2>")
    return html


def _inject_section_body(html: str, h2_text: str, body_html: str) -> str:
    """Find <h2>...h2_text...</h2> in ``html`` and replace the skeleton
    body between it and the next <h2> (or </main>) with ``body_html``.

    Preserves the heading itself. If the heading is not present, append
    a new section at end of <main>.
    """
    pattern = re.compile(
        r"(<h2[^>]*>\s*" + re.escape(h2_text) + r"\s*</h2>)",
        re.IGNORECASE,
    )
    m = pattern.search(html)
    if not m:
        appendix = f"\n<h2>{_html.escape(h2_text)}</h2>\n{body_html}\n"
        if "</main>" in html:
            return html.replace("</main>", appendix + "</main>", 1)
        return html + appendix

    start = m.end()
    next_h2 = re.search(r"<h2[^>]*>", html[start:])
    end_main = html.find("</main>", start)
    if next_h2 and (end_main < 0 or start + next_h2.start() < end_main):
        cutoff = start + next_h2.start()
    elif end_main > 0:
        cutoff = end_main
    else:
        cutoff = len(html)
    return html[:start] + "\n" + body_html + "\n" + html[cutoff:]


def _technical_chart_imgs(payload, *, report_id: int | None) -> str:
    """Build the trailing <figure> block appended to the Technical section.

    Phase 10: matches reference report style — 3 inline <figure> tags,
    each with a <figcaption>. All charts are inline base64 (no backend
    URL dependency) so email + offline viewing both work.

      1. Daily K-line (candlestick + SMA + volume + RSI) — chart_kline_daily_b64
      2. Weekly K-line                                   — chart_kline_weekly_b64
      3. Intraday K-line (short_term / earnings_review)  — chart_kline_intraday_b64
      4. Equity curve (backtest result)                  — chart_equity_curve_b64

    Backwards-compat: if structured only has chart_equity_curve_b64
    (Phase 4-9 reports persisted before this rewrite), we still render
    just that one and skip the K-lines.
    """
    parts: list[str] = []
    structured = payload.structured if payload is not None else None
    if not isinstance(structured, dict):
        return ""

    daily = structured.get("chart_kline_daily_b64")
    weekly = structured.get("chart_kline_weekly_b64")
    intraday = structured.get("chart_kline_intraday_b64")
    equity = structured.get("chart_equity_curve_b64")

    def _fig(src: str, alt: str, caption: str) -> str:
        return (
            f'\n<figure style="margin:1rem 0;">'
            f'<img src="{src}" alt="{alt}" style="max-width:100%;height:auto;">'
            f'<figcaption style="font-size:.85rem;color:var(--muted);margin-top:.3rem;">'
            f'{caption}</figcaption></figure>'
        )

    if daily:
        parts.append(_fig(
            daily,
            "Daily K-line",
            "Daily candlestick with SMA20/50/200 + volume + RSI(14). "
            "Dashed horizontal lines = auto-detected 52-week / 60-day "
            "support and resistance.",
        ))
    if weekly:
        parts.append(_fig(
            weekly,
            "Weekly K-line",
            "Weekly candlestick (resampled to W-FRI) with SMA20/50/200 "
            "and longer-term support/resistance.",
        ))
    if intraday:
        parts.append(_fig(
            intraday,
            "Intraday K-line",
            "Intraday candlestick + volume (5-min bars for short-term "
            "trades, 15-min for earnings review) — recent sessions only.",
        ))
    if equity:
        parts.append(_fig(
            equity,
            "Equity curve",
            "Backtest equity curve — $1 start, compounded by the forward "
            "return at each signal trigger (20-day horizon).",
        ))

    # Backwards compat: old reports persisted with kline-daily.png URL only
    if not (daily or weekly) and report_id is not None:
        parts.append(_fig(
            f"/research/reports/{report_id}/chart/kline-daily.png",
            "Daily K-line",
            "Daily K-line (legacy URL — re-run analyze for inline candlestick).",
        ))

    return "".join(parts)


# 5-level verdict styling. (color, light background) per recommendation.
_VERDICT_STYLE = {
    "strong_buy":  ("#15803d", "#f0fdf4"),
    "buy":         ("#16a34a", "#f0fdf4"),
    "hold":        ("#6b7280", "#f9fafb"),
    "sell":        ("#ea580c", "#fff7ed"),
    "strong_sell": ("#dc2626", "#fef2f2"),
}
_VERDICT_LABEL_EN = {
    "strong_buy": "STRONG BUY", "buy": "BUY", "hold": "HOLD",
    "sell": "SELL", "strong_sell": "STRONG SELL",
}
_VERDICT_LABEL_ZH = {
    "strong_buy": "强力买入", "buy": "买入", "hold": "持有 / 观望",
    "sell": "卖出", "strong_sell": "强力卖出",
}


def _verdict_banner_html(exec_structured: dict, lang: str) -> str:
    """Prominent buy/sell/hold + confidence banner for the top of the report.
    Reads the executive_summary section's structured output."""
    rec = exec_structured.get("recommendation")
    if rec not in _VERDICT_STYLE:
        return ""
    conf = exec_structured.get("confidence_score")
    conf = int(conf) if isinstance(conf, (int, float)) else None
    one_liner = exec_structured.get("overall_view") or ""

    color, bg = _VERDICT_STYLE[rec]
    label = (_VERDICT_LABEL_ZH if lang == "zh" else _VERDICT_LABEL_EN)[rec]
    conf_word = "置信度" if lang == "zh" else "Confidence"
    head_word = "投资建议" if lang == "zh" else "Recommendation"

    conf_html = ""
    if conf is not None:
        conf_html = (
            f'<div style="flex:1;min-width:160px;">'
            f'<div style="font-size:0.75rem;color:#6b7280;text-transform:uppercase;'
            f'letter-spacing:0.05em;">{conf_word}</div>'
            f'<div style="display:flex;align-items:center;gap:8px;">'
            f'<div style="flex:1;height:8px;background:#e5e7eb;border-radius:4px;overflow:hidden;">'
            f'<div style="width:{conf}%;height:100%;background:{color};"></div></div>'
            f'<strong style="color:{color};">{conf}/100</strong></div></div>'
        )

    return (
        f'<div style="border:2px solid {color};border-radius:12px;'
        f'padding:16px 20px;margin:18px 0 28px;background:{bg};">'
        f'<div style="display:flex;align-items:center;gap:20px;flex-wrap:wrap;">'
        f'<div><div style="font-size:0.75rem;color:#6b7280;text-transform:uppercase;'
        f'letter-spacing:0.05em;">{head_word}</div>'
        f'<div style="font-size:1.9rem;font-weight:800;color:{color};line-height:1.1;">'
        f'{label}</div></div>'
        f'{conf_html}</div>'
        f'<div style="margin-top:10px;color:#374151;font-size:0.95rem;">'
        f'{_html.escape(one_liner)}</div></div>'
    )


def render_sop(report: AnalyzeReport, *, report_id: int | None = None) -> str:
    """Render an ``AnalyzeReport`` into a single self-contained HTML
    document using the vendored skill template + per-section body
    injection.

    ``report_id``: when provided, K-line chart <img> tags pointing at
    ``/research/reports/{id}/chart/kline-{kind}.png`` are appended to
    the Technical section body. When None (CLI path), only the inline
    base64 equity-curve image is embedded (no K-line — there is no
    backend to serve it).
    """
    req = report["request"]
    sections = report.get("sections") or {}

    # Pull conviction.total_score for the {{ score }} placeholder.
    score: int | str = "n/a"
    conv = sections.get("conviction")
    if conv and not conv.skipped and isinstance(conv.structured, dict):
        s = conv.structured.get("total_score")
        if isinstance(s, (int, float)):
            score = int(s)

    backtest = report.get("backtest")
    signal_name = backtest.signal if backtest else ""
    backtest_window = ""
    if backtest:
        backtest_window = f"{backtest.window_start} to {backtest.window_end}"

    n_items = sum(
        1 for name, p in sections.items()
        if not name.startswith("_") and not p.skipped
    )

    ctx = {
        "ticker": req.ticker,
        "company_name": req.ticker,  # company name lookup not wired yet
        "exchange": "",
        "sector": "",
        "industry": "",
        "report_datetime": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "quote_timestamp": "",
        "filing_date": "",
        "chart_window": "",
        "backtest_window": backtest_window,
        "depth": "full SOP",
        "objective": req.objective,
        "position_budget_or_na": (
            f"${req.position_budget_usd:,.0f}"
            if req.position_budget_usd else "n/a"
        ),
        "risk_profile": req.risk_tolerance,
        "score": str(score),
        "score_conservative": "",
        "score_balanced": "",
        "score_aggressive": "",
        "signal_name": signal_name,
        "n_items": str(n_items),
        "backtest_bundle_path": "",
        "placeholder": "",
    }

    html = _ENV.get_template("report.html").render(**ctx)

    # Inject every section body, in canonical order. The body REPLACES
    # any scalar Jinja placeholders the template had inside that section
    # (e.g. {{ score }} inside the Conviction table); we re-emit a
    # score badge below so the always-75 fix is still visible in HTML.
    for section_name, h2_text in _HEADING_MAP.items():
        payload = sections.get(section_name)
        if payload is None:
            continue
        body_html = _markdown_to_html(payload.markdown or "", skip_h2=True)
        if section_name == "conviction" and score != "n/a":
            label = "总分" if getattr(req, "report_language", "en") == "zh" else "Total score"
            body_html += (
                f'\n<p><strong>{label}:</strong> '
                f'<span class="score-badge">{score}/100</span></p>'
            )
        if section_name == "technical":
            body_html += _technical_chart_imgs(payload, report_id=report_id)
        html = _inject_section_body(html, h2_text, body_html)

    # Append appendix sections (no <h2> in skeleton).
    for section_name, h2_text in _APPENDIX_SECTIONS.items():
        payload = sections.get(section_name)
        if payload is None:
            continue
        body_html = _markdown_to_html(payload.markdown or "", skip_h2=True)
        html = _inject_section_body(html, h2_text, body_html)

    # Phase 11.1 fix: localize the template's hardcoded English <h2>
    # headings to Chinese when report_language=='zh'.
    html = _localize_template_headings(html, getattr(req, "report_language", "en"))

    # Verdict banner — buy/sell/hold + confidence at the very top, for
    # readers who won't scroll the full report. Injected after the header.
    exec_p = sections.get("executive_summary")
    if exec_p and not exec_p.skipped and isinstance(exec_p.structured, dict):
        banner = _verdict_banner_html(
            exec_p.structured, getattr(req, "report_language", "en")
        )
        if banner:
            html = html.replace("</header>", "</header>\n" + banner, 1)

    return html


# ===========================================================================
# Phase 3: render_html(ResearchState) — preserved until Task 19 swaps callers
# ===========================================================================

def _format_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:+.1f}"


def _persona_assignments_block(assignments: dict | None) -> str:
    """Render per-module persona assignments as an inline list (HTML)."""
    if not assignments:
        return ""
    parts: list[str] = []
    for module_name in ("fundamentals", "valuation", "risk_position"):
        persona = assignments.get(module_name)
        label = persona if persona else "objective"
        parts.append(
            f'<div><strong>{_html.escape(module_name)}:</strong> '
            f'{_html.escape(label)}</div>'
        )
    debate = assignments.get("debate") or []
    if isinstance(debate, list) and len(debate) == 2:
        parts.append(
            f'<div><strong>debate:</strong> '
            f'{_html.escape(debate[0])} vs {_html.escape(debate[1])}</div>'
        )
    return "\n".join(parts)


def render_html(state: ResearchState) -> str:
    """Convert a ResearchState into the final HTML payload.

    Phase 3 API. Kept until Task 19 migrates the last caller
    (app/backend/routes/research.py + scheduler_service.py) onto
    ``render_sop(AnalyzeReport)``.
    """
    request = state["request"]
    plan = state["strategy"]
    backtest = state["backtest_summary"]
    module_results = state.get("module_results") or {}
    assignments = state.get("persona_assignments")

    module_blocks: list[tuple[str, str]] = []
    for name, result in module_results.items():
        if result.skipped:
            continue
        if not result.markdown.strip():
            continue
        module_blocks.append((name, _markdown_to_html(result.markdown)))

    persona_per_module = {}
    if assignments:
        for name, result in module_results.items():
            if result.persona_used:
                persona_per_module[name] = result.persona_used

    ctx = {
        "ticker": request.ticker,
        "scan_date": (request.scanner_context or {}).get("scan_date", "") if request.scanner_context else "",
        "report_goal": request.report_goal,
        "risk_tolerance": request.risk_tolerance,
        "holding_status": request.holding_status,
        "plan_direction": plan.direction,
        "plan_entry": f"{plan.entry_price:.2f}" if plan.entry_price is not None else "—",
        "plan_target": f"{plan.target_price:.2f}" if plan.target_price is not None else "—",
        "plan_stop": f"{plan.stop_price:.2f}" if plan.stop_price is not None else "—",
        "plan_horizon": plan.horizon_days,
        "plan_sizing_pct": f"{plan.sizing_pct * 100:.2f}",
        "plan_confidence": plan.confidence,
        "plan_rationale": plan.rationale,
        "backtest_sample_quality": backtest.sample_quality,
        "backtest_matches": backtest.matches_found,
        "backtest_win_rate": _format_pct(backtest.win_rate),
        "backtest_avg_pnl": _format_pct(backtest.avg_pnl_pct),
        "backtest_max_dd": _format_pct(backtest.max_drawdown_pct),
        "backtest_caveat": backtest.caveat or "",
        "persona_assignments_block": _persona_assignments_block(assignments),
        "persona_rationale": (assignments or {}).get("_rationale", "") or "",
        "persona_per_module": persona_per_module,
        "report_html": _markdown_to_html(state.get("report_markdown") or ""),
        "module_blocks": module_blocks,
        "duration_seconds": "—",
    }
    template = _ENV.get_template("report.html")
    return template.render(**ctx)
