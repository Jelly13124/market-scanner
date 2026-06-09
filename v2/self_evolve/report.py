"""Run report for the self-evolve loop — the iteration path + the TEST verdict.

After :func:`v2.self_evolve.loop.evolve` has driven the keep/rollback search and
the caller has run the SINGLE post-loop ``backtest(..., "test")`` on the held-out
sample, this module renders the human-readable readout:

* :func:`render_iteration_path_png` — a step/line chart of validation Sharpe
  across the optimization path (every ``v0`` / ``v0.0.<r>`` entry), kept versions
  drawn as filled markers, rolled-back ones hollow. Best-effort: a sparse / empty
  / malformed path log renders a placeholder PNG rather than raising.
* :func:`write_report` — writes ``self_evolve_report.md`` + ``.html`` containing
  the iteration-path table (val Sharpe per version + kept flag), the embedded
  PNG, the retained-best config, and the TEST verdict (the ``test_metrics`` dict
  the caller computed once on the held-out sample). It returns the two paths plus
  the extracted ``test_sharpe``.

The report is deliberately honest about what it does and does NOT prove: a higher
validation Sharpe is the loop's *selection objective*, not evidence of a real
edge. The held-out test readout and a paper forward-test are the judges — stated
verbatim in the report so a reader is never misled.

Reuses the matplotlib-Agg + ``png_to_b64_uri`` primitives from
:mod:`src.research.charts.render`. Pure rendering + I/O — no network, no LLM, no
loop logic of its own (it reads the already-written path log via
:mod:`v2.self_evolve.versioning`).
"""

from __future__ import annotations

import html as _html
import io
import logging
import os
from dataclasses import asdict, is_dataclass

import matplotlib

matplotlib.use("Agg")  # noqa: E402 — backend selection must precede pyplot import

import matplotlib.pyplot as plt  # noqa: E402

from src.research.charts.render import png_to_b64_uri  # noqa: E402
from v2.self_evolve.versioning import read_path_log  # noqa: E402

logger = logging.getLogger(__name__)

_FIGSIZE = (10, 5)
_DPI = 90

#: The honest caveat, stated verbatim in both the md and html reports.
_CAVEAT = "Honest note: val improvement != proven edge. The retained config was chosen " "to maximize VALIDATION Sharpe; that is the search objective, not evidence of " "an edge. The held-out test readout below and a paper forward-test are the " "judges."


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _no_data_png(message: str = "No iteration data") -> bytes:
    """A tiny placeholder PNG so callers always get valid bytes."""
    fig, ax = plt.subplots(figsize=_FIGSIZE, dpi=_DPI)
    ax.text(0.5, 0.5, message, ha="center", va="center", transform=ax.transAxes, fontsize=14, color="#9ca3af")
    ax.set_axis_off()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=_DPI, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _num(x):
    """Coerce to float, or ``None`` for missing / non-numeric / NaN."""
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    return v


def _fmt(x, *, pct=False, raw_pct=False, digits=3):
    """Format a metric for the tables; ``-`` for missing / NaN.

    ``pct`` multiplies by 100 (a ratio → percent); ``raw_pct`` formats a value
    that is ALREADY a percent (e.g. ``max_drawdown`` from the metrics calculator).
    """
    v = _num(x)
    if v is None:
        return "-"
    if raw_pct:
        return f"{v:.2f}%"
    if pct:
        return f"{v * 100:.2f}%"
    return f"{v:.{digits}f}"


def _config_dict(best_config) -> dict:
    """Best-effort config → plain dict (dataclass, mapping, or attr bag)."""
    if best_config is None:
        return {}
    if is_dataclass(best_config) and not isinstance(best_config, type):
        return asdict(best_config)
    if isinstance(best_config, dict):
        return dict(best_config)
    # Duck-typed: pull the fields generate_holdings cares about, if present.
    out = {}
    for name in ("factor_weights", "lookback", "top_n", "holding_buffer", "max_weight", "liquidity_pct", "tilt_strength", "rebalance", "cost_bps"):
        if hasattr(best_config, name):
            out[name] = getattr(best_config, name)
    return out


# ---------------------------------------------------------------------------
# iteration-path chart
# ---------------------------------------------------------------------------


def render_iteration_path_png(path_log) -> bytes:
    """Step chart of validation Sharpe across the optimization path.

    ``path_log`` is the list of ``{v_id, hypothesis, val_sharpe, kept}`` entries
    returned by :func:`v2.self_evolve.loop.evolve`. The x-axis is the iteration
    index (path order); the y-axis is each version's validation Sharpe. KEPT
    versions are drawn as filled green markers, rolled-back ones as hollow red.
    A monotonically rising "running-best" step line traces the best val Sharpe
    kept so far.

    Best-effort: an empty path, or one with no numeric Sharpe anywhere, renders a
    placeholder PNG. NEVER raises.
    """
    try:
        entries = list(path_log or [])
        xs = list(range(len(entries)))
        sharpes = [_num(e.get("val_sharpe")) for e in entries]
        kept = [bool(e.get("kept")) for e in entries]
        labels = [str(e.get("v_id", "")) for e in entries]

        if not entries or all(s is None for s in sharpes):
            return _no_data_png()

        fig, ax = plt.subplots(figsize=_FIGSIZE, dpi=_DPI)

        # The candidate val Sharpe at each step (gaps where Sharpe is missing).
        ys = [s if s is not None else float("nan") for s in sharpes]
        ax.plot(xs, ys, color="#9ca3af", linewidth=1.0, linestyle="-", zorder=1, label="candidate val Sharpe")

        # Running-best step line: the highest kept val Sharpe seen up to each step.
        best = float("-inf")
        best_curve: list[float] = []
        for s, k in zip(sharpes, kept):
            if k and s is not None and s > best:
                best = s
            best_curve.append(best if best != float("-inf") else float("nan"))
        ax.step(xs, best_curve, where="post", color="#2563eb", linewidth=1.6, zorder=2, label="running-best (kept)")

        # Kept vs rolled-back markers.
        for x, s, k in zip(xs, sharpes, kept):
            if s is None:
                continue
            if k:
                ax.scatter([x], [s], s=70, color="#16a34a", edgecolor="#065f46", zorder=3)
            else:
                ax.scatter([x], [s], s=60, facecolors="none", edgecolors="#dc2626", linewidths=1.4, zorder=3)

        ax.set_title("Self-Evolve Iteration Path — validation Sharpe per version", fontsize=11)
        ax.set_xlabel("Iteration (version order)")
        ax.set_ylabel("Validation Sharpe")
        ax.set_xticks(xs)
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
        ax.axhline(0.0, color="#cbd5e1", linewidth=0.6, linestyle=":")
        ax.grid(True, alpha=0.3)

        # A small legend distinguishing kept vs rolled-back markers.
        from matplotlib.lines import Line2D

        handles = [
            Line2D([0], [0], color="#2563eb", linewidth=1.6, label="running-best (kept)"),
            Line2D([0], [0], marker="o", color="w", markerfacecolor="#16a34a", markeredgecolor="#065f46", markersize=9, label="kept"),
            Line2D([0], [0], marker="o", color="w", markerfacecolor="none", markeredgecolor="#dc2626", markersize=9, label="rolled back"),
        ]
        ax.legend(handles=handles, loc="best", fontsize=8)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=_DPI, bbox_inches="tight")
        plt.close(fig)
        return buf.getvalue()
    except Exception as exc:  # rendering must never crash the run.
        logger.warning("render_iteration_path_png failed; using placeholder: %s", exc)
        try:
            return _no_data_png("Chart render failed")
        except Exception:
            # Absolute last resort — a 1x1 transparent PNG so callers still get bytes.
            return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01" b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01" b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"


# ---------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------


def _iteration_rows(path_log) -> list[tuple[str, str, str, str]]:
    """``(v_id, val_sharpe, kept, hypothesis)`` strings for the path table."""
    rows: list[tuple[str, str, str, str]] = []
    for e in path_log or []:
        vid = str(e.get("v_id", ""))
        vs = _fmt(e.get("val_sharpe"))
        kept = "kept" if e.get("kept") else "rolled back"
        hyp = str(e.get("hypothesis", "") or "")
        rows.append((vid, vs, kept, hyp))
    return rows


def _config_table_md(cfg: dict) -> list[str]:
    """Markdown bullet list of the retained config (nested dicts flattened)."""
    lines: list[str] = []
    for key in sorted(cfg):
        val = cfg[key]
        if isinstance(val, dict):
            inner = ", ".join(f"{k}={v}" for k, v in val.items())
            lines.append(f"- **{key}**: {inner}")
        else:
            lines.append(f"- **{key}**: {val}")
    return lines


def write_report(out_dir, *, base_dir, bundles, best_config, test_metrics) -> dict:
    """Write the self-evolve run report (md + html) and return the artifact paths.

    Parameters
    ----------
    out_dir
        Directory to write ``self_evolve_report.md`` / ``.html`` into (created).
    base_dir
        The loop's version store; its ``path_log.jsonl`` is read for the
        iteration path (val Sharpe per version + kept flag).
    bundles
        ``{ticker: bundle}`` the run used — only its SIZE (universe count) is
        reported, for context. Never indexed into.
    best_config
        The retained-best config (the last KEPT version's config). A dataclass,
        mapping, or attr-bag is all accepted.
    test_metrics
        The dict from the SINGLE post-loop ``backtest(bundles, best_config,
        "test")`` — the held-out verdict (``sharpe`` / ``ann_return`` /
        ``max_drawdown`` / ``turnover`` / ``n_rebalances``).

    Returns
    -------
    dict
        ``{"report_md": <path>, "report_html": <path>, "test_sharpe": <float|None>}``.

    Never crashes on a sparse run: an empty path log, a degenerate config, or a
    ``None`` test metric all render cleanly (with ``-`` / placeholder fallbacks).
    """
    os.makedirs(out_dir, exist_ok=True)
    md_path = os.path.join(out_dir, "self_evolve_report.md")
    html_path = os.path.join(out_dir, "self_evolve_report.html")

    path_log = read_path_log(base_dir)
    rows = _iteration_rows(path_log)
    cfg = _config_dict(best_config)
    tm = test_metrics or {}
    test_sharpe = _num(tm.get("sharpe"))
    n_kept = sum(1 for e in path_log if e.get("kept"))
    n_universe = len(bundles) if bundles else 0

    png = render_iteration_path_png(path_log)
    data_uri = png_to_b64_uri(png)

    # -- Markdown ----------------------------------------------------------
    md: list[str] = []
    md.append("# Self-Evolve Run Report")
    md.append("")
    md.append(f"- universe size: {n_universe}")
    md.append(f"- versions on path: {len(path_log)} ({n_kept} kept)")
    md.append("")
    md.append(f"> {_CAVEAT}")
    md.append("")

    md.append("## Iteration path (validation Sharpe per version)")
    md.append("")
    md.append("| version | val_sharpe | status | hypothesis |")
    md.append("|---|---|---|---|")
    if rows:
        for vid, vs, kept, hyp in rows:
            md.append(f"| {vid} | {vs} | {kept} | {hyp} |")
    else:
        md.append("| (no versions) | | | |")
    md.append("")
    md.append("![iteration path](self_evolve_iteration_path.png)")
    md.append("")

    md.append("## Retained-best config")
    md.append("")
    cfg_lines = _config_table_md(cfg)
    md.extend(cfg_lines if cfg_lines else ["- (no config)"])
    md.append("")

    md.append("## TEST verdict (held-out sample — read once, post-loop)")
    md.append("")
    md.append("| metric | value |")
    md.append("|---|---|")
    md.append(f"| sharpe | {_fmt(tm.get('sharpe'))} |")
    md.append(f"| ann_return | {_fmt(tm.get('ann_return'), pct=True)} |")
    md.append(f"| ann_vol | {_fmt(tm.get('ann_vol'), pct=True)} |")
    md.append(f"| max_drawdown | {_fmt(tm.get('max_drawdown'), raw_pct=True)} |")
    md.append(f"| turnover | {_fmt(tm.get('turnover'))} |")
    md.append(f"| n_rebalances | {tm.get('n_rebalances', '-')} |")
    md.append("")

    md_text = "\n".join(md)
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(md_text)

    # The PNG referenced by the markdown (sibling file). Best-effort.
    try:
        with open(os.path.join(out_dir, "self_evolve_iteration_path.png"), "wb") as fh:
            fh.write(png)
    except OSError as exc:  # pragma: no cover - disk failure only
        logger.warning("could not write iteration-path PNG: %s", exc)

    # -- HTML --------------------------------------------------------------
    def esc(x) -> str:
        return _html.escape(str(x))

    h: list[str] = []
    h.append("<!doctype html><html><head><meta charset='utf-8'>")
    h.append("<title>Self-Evolve Run Report</title>")
    h.append(
        "<style>body{font-family:-apple-system,Segoe UI,Arial,sans-serif;margin:2rem;color:#111;}"
        "table{border-collapse:collapse;margin:1rem 0;}"
        "th,td{border:1px solid #d1d5db;padding:6px 10px;text-align:left;font-size:14px;}"
        "th{background:#f3f4f6;} code{background:#f3f4f6;padding:1px 4px;border-radius:3px;}"
        ".caveat{background:#fef3c7;border-left:4px solid #f59e0b;padding:10px 14px;margin:1rem 0;}"
        "img{max-width:100%;height:auto;border:1px solid #e5e7eb;}</style>"
    )
    h.append("</head><body>")
    h.append("<h1>Self-Evolve Run Report</h1>")
    h.append(f"<p>universe size: <b>{n_universe}</b> &middot; versions on path: <b>{len(path_log)}</b> ({n_kept} kept)</p>")
    h.append(f"<div class='caveat'>{esc(_CAVEAT)}</div>")

    h.append("<h2>Iteration path (validation Sharpe per version)</h2>")
    h.append("<table><thead><tr><th>version</th><th>val_sharpe</th><th>status</th><th>hypothesis</th></tr></thead><tbody>")
    if rows:
        for vid, vs, kept, hyp in rows:
            h.append(f"<tr><td>{esc(vid)}</td><td>{esc(vs)}</td><td>{esc(kept)}</td><td>{esc(hyp)}</td></tr>")
    else:
        h.append("<tr><td colspan='4'>(no versions)</td></tr>")
    h.append("</tbody></table>")
    h.append(f"<img src='{data_uri}' alt='iteration path'/>")

    h.append("<h2>Retained-best config</h2>")
    h.append("<ul>")
    if cfg:
        for key in sorted(cfg):
            val = cfg[key]
            if isinstance(val, dict):
                inner = ", ".join(f"{esc(k)}={esc(v)}" for k, v in val.items())
                h.append(f"<li><b>{esc(key)}</b>: {inner}</li>")
            else:
                h.append(f"<li><b>{esc(key)}</b>: {esc(val)}</li>")
    else:
        h.append("<li>(no config)</li>")
    h.append("</ul>")

    h.append("<h2>TEST verdict (held-out sample — read once, post-loop)</h2>")
    h.append("<table><thead><tr><th>metric</th><th>value</th></tr></thead><tbody>")
    h.append(f"<tr><td>sharpe</td><td>{esc(_fmt(tm.get('sharpe')))}</td></tr>")
    h.append(f"<tr><td>ann_return</td><td>{esc(_fmt(tm.get('ann_return'), pct=True))}</td></tr>")
    h.append(f"<tr><td>ann_vol</td><td>{esc(_fmt(tm.get('ann_vol'), pct=True))}</td></tr>")
    h.append(f"<tr><td>max_drawdown</td><td>{esc(_fmt(tm.get('max_drawdown'), raw_pct=True))}</td></tr>")
    h.append(f"<tr><td>turnover</td><td>{esc(_fmt(tm.get('turnover')))}</td></tr>")
    h.append(f"<tr><td>n_rebalances</td><td>{esc(tm.get('n_rebalances', '-'))}</td></tr>")
    h.append("</tbody></table>")
    h.append("</body></html>")

    html_text = "".join(h)
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(html_text)

    return {"report_md": md_path, "report_html": html_path, "test_sharpe": test_sharpe}
