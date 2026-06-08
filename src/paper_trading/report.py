"""Human-readable performance report for the paper-trading forward test (Task 7).

Tasks 5/6 persist a daily :class:`PaperEquityMark` per ``(sleeve, date)`` and
derive the comparable A/B numbers + graduation verdict. This module renders that
state for a human: a per-sleeve metrics table, the graduation verdict, and a
single equity-curve chart overlaying all three sleeves, written out as both a
Markdown and an HTML file (the chart is embedded inline as a base64 data URI so
the HTML is self-contained).

Charting follows the headless matplotlib pattern of ``src/research/charts/render.py``
exactly: ``matplotlib.use("Agg")`` is selected before pyplot is imported, the
shared ``_DPI``/``_FIGSIZE_DEFAULT`` constants size the figure, and every figure
is closed after ``savefig``. The base64 embedding reuses that module's
``png_to_b64_uri`` rather than re-deriving the data-URI prefix.

Robustness contract (mirrors the rest of the harness): nothing here raises.
``render_sleeves_equity_png`` returns a small "No data" placeholder PNG on
empty/all-empty input, and ``write_report`` still writes a near-empty report
against a sparse or empty DB rather than crashing.
"""

from __future__ import annotations

import datetime as _dt
import html as _html
import io
import logging
import os

import matplotlib

matplotlib.use("Agg")  # noqa: E402 — backend selection must precede pyplot import

import matplotlib.pyplot as plt  # noqa: E402

from sqlalchemy.orm import Session  # noqa: E402

from app.backend.database.models import PaperEquityMark, PaperSleeve  # noqa: E402
from src.paper_trading.performance import (  # noqa: E402
    compute_performance,
    evaluate_graduation,
)
from src.research.charts.render import png_to_b64_uri  # noqa: E402

logger = logging.getLogger(__name__)

_FIGSIZE_DEFAULT = (10, 6)
_DPI = 90

# A stable colour per sleeve so the same book is the same line across reports;
# unknown sleeve names fall through to the matplotlib default cycle.
_SLEEVE_COLORS = {
    "scanner_agent": "#2563eb",
    "scanner_only": "#f59e0b",
    "spy_benchmark": "#16a34a",
}

# The known sleeves in their canonical A/B order; any extra sleeves render after.
_SLEEVE_ORDER = ["scanner_agent", "scanner_only", "spy_benchmark"]


def _no_data_png(message: str = "No data") -> bytes:
    """Render a tiny placeholder PNG so callers always get valid bytes."""
    fig, ax = plt.subplots(figsize=_FIGSIZE_DEFAULT, dpi=_DPI)
    ax.text(
        0.5,
        0.5,
        message,
        ha="center",
        va="center",
        transform=ax.transAxes,
        fontsize=14,
        color="#9ca3af",
    )
    ax.set_axis_off()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=_DPI, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _parse_dates(date_strs: list[str]) -> list | None:
    """Parse ``YYYY-MM-DD`` strings to dates for the x-axis.

    Returns ``None`` (so the caller falls back to a plain integer index) if any
    entry can't be parsed — the chart is best-effort and an index axis is a fine
    degradation from real dates.
    """
    out: list = []
    for s in date_strs:
        try:
            out.append(_dt.datetime.fromisoformat(str(s)[:10]))
        except (TypeError, ValueError):
            return None
    return out


def render_sleeves_equity_png(equity_by_sleeve: dict[str, list[tuple[str, float]]]) -> bytes:
    """Overlay every sleeve's equity curve on one headless matplotlib figure.

    Args:
        equity_by_sleeve: ``{sleeve_name: [(date_str, equity), ...]}`` already
            sorted by date. Sleeves with an empty series are skipped.

    Returns:
        PNG bytes. Empty input, or input where every sleeve series is empty,
        yields a small "No data" placeholder PNG. Never raises.
    """
    try:
        # Drop empty series up front; if nothing is plottable, short-circuit.
        plottable = {name: pts for name, pts in (equity_by_sleeve or {}).items() if pts}
        if not plottable:
            return _no_data_png("No equity marks yet")

        # Canonical sleeves first (stable colour + legend order), then any extras.
        ordered_names = [n for n in _SLEEVE_ORDER if n in plottable]
        ordered_names += [n for n in plottable if n not in _SLEEVE_ORDER]

        fig, ax = plt.subplots(figsize=_FIGSIZE_DEFAULT, dpi=_DPI)
        for name in ordered_names:
            pts = plottable[name]
            dates = [p[0] for p in pts]
            equities = [float(p[1]) for p in pts]
            xs = _parse_dates(dates)
            if xs is None:
                xs = list(range(len(equities)))
            ax.plot(
                xs,
                equities,
                linewidth=1.6,
                label=name,
                color=_SLEEVE_COLORS.get(name),
            )

        ax.set_title("Paper sleeves — equity ($100k start)", fontsize=11)
        ax.set_ylabel("Equity ($)")
        ax.set_xlabel("Date")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best", fontsize=9)
        fig.autofmt_xdate()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=_DPI, bbox_inches="tight")
        plt.close(fig)
        return buf.getvalue()
    except Exception:
        logger.exception("render_sleeves_equity_png failed; returning placeholder")
        return _no_data_png("Chart render failed")


def _load_equity_by_sleeve(session: Session) -> dict[str, list[tuple[str, float]]]:
    """Load each sleeve's equity marks (date-ordered) into the chart's shape."""
    out: dict[str, list[tuple[str, float]]] = {}
    sleeves = session.query(PaperSleeve).all()
    for sleeve in sleeves:
        marks = session.query(PaperEquityMark).filter_by(sleeve_id=sleeve.id).order_by(PaperEquityMark.date).all()
        out[sleeve.name] = [(m.date, float(m.equity)) for m in marks]
    return out


def _fmt_pct_return(total_return) -> str:
    """``total_return`` is a fraction (0.05 -> '+5.00%'); None -> 'n/a'."""
    if total_return is None:
        return "n/a"
    return f"{total_return * 100.0:+.2f}%"


def _fmt_drawdown(max_drawdown) -> str:
    """``max_drawdown`` is ALREADY a ×100 percent — show with %, do NOT ×100."""
    if max_drawdown is None:
        return "n/a"
    return f"{max_drawdown:.2f}%"


def _fmt_num(value, decimals: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{decimals}f}"


def _fmt_money(value) -> str:
    if value is None:
        return "n/a"
    return f"${value:,.2f}"


_TABLE_HEADERS = [
    "Sleeve",
    "Total return",
    "Sharpe",
    "Max drawdown",
    "# Trades",
    "Final equity",
    "# Marks",
]


def _row_cells(name: str, m: dict) -> list[str]:
    return [
        name,
        _fmt_pct_return(m.get("total_return")),
        _fmt_num(m.get("sharpe")),
        _fmt_drawdown(m.get("max_drawdown")),
        str(m.get("n_trades", 0)),
        _fmt_money(m.get("final_equity")),
        str(m.get("n_marks", 0)),
    ]


def _ordered_perf_items(perf: dict[str, dict]) -> list[tuple[str, dict]]:
    """Canonical sleeves first, then any extras — stable table/legend order."""
    names = [n for n in _SLEEVE_ORDER if n in perf]
    names += [n for n in perf if n not in _SLEEVE_ORDER]
    return [(n, perf[n]) for n in names]


def _render_markdown(perf: dict, verdict: dict, chart_uri: str) -> str:
    lines: list[str] = []
    lines.append("# Paper Trading Forward-Test Report")
    lines.append("")
    lines.append(f"_Generated {_dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_")
    lines.append("")

    # Metrics table.
    lines.append("## Per-sleeve metrics")
    lines.append("")
    lines.append("| " + " | ".join(_TABLE_HEADERS) + " |")
    lines.append("| " + " | ".join(["---"] * len(_TABLE_HEADERS)) + " |")
    items = _ordered_perf_items(perf)
    if items:
        for name, m in items:
            lines.append("| " + " | ".join(_row_cells(name, m)) + " |")
    else:
        lines.append("| _no sleeves_ |" + " |" * (len(_TABLE_HEADERS) - 1))
    lines.append("")

    # Graduation verdict.
    lines.append("## Graduation verdict")
    lines.append("")
    lines.append(f"**Result: {'PASS' if verdict.get('passed') else 'FAIL'}** " f"(passed={verdict.get('passed')})")
    lines.append("")
    for reason in verdict.get("reasons", []):
        lines.append(f"- {reason}")
    if not verdict.get("reasons"):
        lines.append("- _no clauses evaluated_")
    lines.append("")

    # Equity chart — embed the data URI inline; the HTML renders it natively.
    lines.append("## Equity curve")
    lines.append("")
    lines.append("The 3-sleeve equity chart is embedded in the HTML report " "(`paper_trading_report.html`). Inline data URI:")
    lines.append("")
    lines.append(f"![Paper sleeves equity]({chart_uri})")
    lines.append("")
    return "\n".join(lines)


def _render_html(perf: dict, verdict: dict, chart_uri: str) -> str:
    passed = bool(verdict.get("passed"))
    verdict_word = "PASS" if passed else "FAIL"
    verdict_color = "#16a34a" if passed else "#e11d48"

    head_cells = "".join(f"<th>{_html.escape(h)}</th>" for h in _TABLE_HEADERS)
    body_rows: list[str] = []
    items = _ordered_perf_items(perf)
    if items:
        for name, m in items:
            cells = "".join(f"<td>{_html.escape(c)}</td>" for c in _row_cells(name, m))
            body_rows.append(f"<tr>{cells}</tr>")
    else:
        body_rows.append(f'<tr><td colspan="{len(_TABLE_HEADERS)}"><em>no sleeves</em></td></tr>')

    reason_items = "".join(f"<li>{_html.escape(r)}</li>" for r in verdict.get("reasons", [])) or "<li><em>no clauses evaluated</em></li>"

    generated = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Paper Trading Forward-Test Report</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif;
          margin: 2rem; color: #111827; }}
  h1 {{ font-size: 1.5rem; }}
  h2 {{ font-size: 1.15rem; margin-top: 1.75rem; border-bottom: 1px solid #e5e7eb;
        padding-bottom: 0.25rem; }}
  table {{ border-collapse: collapse; margin: 0.5rem 0; }}
  th, td {{ border: 1px solid #d1d5db; padding: 6px 12px; text-align: right; }}
  th:first-child, td:first-child {{ text-align: left; }}
  th {{ background: #f3f4f6; }}
  .verdict {{ font-weight: 700; color: {verdict_color}; font-size: 1.1rem; }}
  .muted {{ color: #6b7280; font-size: 0.85rem; }}
  img {{ max-width: 100%; height: auto; border: 1px solid #e5e7eb; }}
</style>
</head>
<body>
  <h1>Paper Trading Forward-Test Report</h1>
  <p class="muted">Generated {generated}</p>

  <h2>Per-sleeve metrics</h2>
  <table>
    <thead><tr>{head_cells}</tr></thead>
    <tbody>{"".join(body_rows)}</tbody>
  </table>

  <h2>Graduation verdict</h2>
  <p class="verdict">Result: {verdict_word} (passed={passed})</p>
  <ul>{reason_items}</ul>

  <h2>Equity curve</h2>
  <img src="{chart_uri}" alt="Paper sleeves equity ($100k start)">
</body>
</html>
"""


def write_report(out_dir: str, *, session: Session) -> dict:
    """Render the full forward-test report to Markdown + HTML in ``out_dir``.

    Computes :func:`compute_performance` + :func:`evaluate_graduation`, loads each
    sleeve's equity marks, renders the 3-sleeve equity chart inline, and writes
    ``paper_trading_report.md`` and ``paper_trading_report.html`` (creating
    ``out_dir`` if needed).

    Args:
        out_dir: Directory to write the two report files into (created if absent).
        session: SQLAlchemy session for the paper-trading tables.

    Returns:
        ``{"report_md": <path>, "report_html": <path>, "passed": <bool>}``.
        Never raises on a sparse/empty DB — it simply writes a near-empty report.
    """
    os.makedirs(out_dir, exist_ok=True)

    perf = compute_performance(session)
    verdict = evaluate_graduation(perf)
    equity_by_sleeve = _load_equity_by_sleeve(session)

    chart_png = render_sleeves_equity_png(equity_by_sleeve)
    chart_uri = png_to_b64_uri(chart_png)

    md_path = os.path.join(out_dir, "paper_trading_report.md")
    html_path = os.path.join(out_dir, "paper_trading_report.html")

    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(_render_markdown(perf, verdict, chart_uri))
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(_render_html(perf, verdict, chart_uri))

    return {
        "report_md": md_path,
        "report_html": html_path,
        "passed": bool(verdict.get("passed")),
    }
