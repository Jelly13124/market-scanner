"""Render a ResearchState into a single self-contained HTML document.

Inline-style HTML; no external CSS or JS. Email-safe (Gmail strips
<style> blocks for some flows — every visual rule that matters is also
inlined on the body element).

Markdown bodies (report_markdown, module markdowns) are converted to
HTML via a minimal markdown-to-HTML pass. We avoid pulling in a heavy
markdown dependency by handling the small subset the synthesizer emits:
headings (#, ##, ###), bold (**), italic (*), bullet lists, paragraphs.
Anything more exotic is left literal.
"""

from __future__ import annotations

import html as _html
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.research.models import ResearchState


_TEMPLATE_DIR = Path(__file__).parent / "templates"
_ENV = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _markdown_to_html(text: str) -> str:
    """Minimal markdown subset → HTML. Handles what the synthesizer +
    module prompts realistically emit; does not pretend to be CommonMark.
    """
    if not text:
        return ""
    # Escape first; then unescape the few markdown markers we re-introduce
    # as real HTML below.
    out_lines: list[str] = []
    in_list = False

    def _inline(s: str) -> str:
        # Order matters: bold before italic to avoid ** being consumed by *.
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<![*\w])\*([^*\n]+?)\*(?!\w)", r"<em>\1</em>", s)
        s = re.sub(r"`([^`]+?)`", r"<code>\1</code>", s)
        return s

    for raw in text.split("\n"):
        line = raw.rstrip()
        escaped = _html.escape(line)
        if not line.strip():
            if in_list:
                out_lines.append("</ul>")
                in_list = False
            out_lines.append("")
            continue
        # Headings (# ## ###)
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            if in_list:
                out_lines.append("</ul>")
                in_list = False
            level = len(m.group(1))
            content = _inline(_html.escape(m.group(2)))
            out_lines.append(f"<h{level + 2}>{content}</h{level + 2}>")
            continue
        # Bullet list item
        if line.lstrip().startswith(("- ", "* ")):
            if not in_list:
                out_lines.append("<ul>")
                in_list = True
            item = line.lstrip()[2:]
            out_lines.append(f"  <li>{_inline(_html.escape(item))}</li>")
            continue
        # Paragraph line
        if in_list:
            out_lines.append("</ul>")
            in_list = False
        out_lines.append(f"<p>{_inline(escaped)}</p>")
    if in_list:
        out_lines.append("</ul>")
    return "\n".join(out_lines)


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
    """Convert a ResearchState into the final HTML payload."""
    request = state["request"]
    plan = state["strategy"]
    backtest = state["backtest_summary"]
    module_results = state.get("module_results") or {}
    assignments = state.get("persona_assignments")

    # Module section list — skip skipped modules
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
        "duration_seconds": "—",  # populated by caller when available
    }
    template = _ENV.get_template("report.html")
    return template.render(**ctx)
