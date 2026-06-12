"""Run-report renderer for the scanner self-evolve loop.

This is the LAST mile of a scanner-evolve run: it turns the on-disk version store
(``read_path_log`` + per-version ``read_version`` under ``base_dir``) plus the
single post-loop held-out ``test`` read into a human-readable run report. Like
the eval report (:mod:`v2.scanner.eval.report`), clarity beats cleverness — the
user reads this to understand what the loop did and whether to believe it.

THE FRAMING (load-bearing)
--------------------------
A higher VALIDATION ``diff`` is a SEARCH SIGNAL, not proven edge. Self-evolution
optimizes within the bounded detector-threshold space — it can find a config that
screens the universe better than chance on the regimes it saw, but it does NOT
create edge that wasn't reachable in that space. The held-out ``test`` sample is a
SINGLE read, and even that is not the verdict: the LIVE scanner forward-test is.
The honest-caveat block states this plainly and is REQUIRED.

A NOTE ON val metrics (load-bearing)
------------------------------------
The loop's ``path_log`` hardcodes ``val_sharpe = val_m.get("sharpe")``, which is
``None`` for scanner metrics. So the per-round val numbers (``diff`` / ``n_fired``
/ ``t_stat``) are read from each round's ``read_version(...)["val_metrics"]`` —
NOT from the path log. The path log is used only for the ``v_id`` order + the
``kept`` flags.

Pure rendering: deterministic, ``generated_at`` is an argument (this module never
calls ``datetime.now()``), and it never raises on a partially-populated store
(best-effort, like the versioning readers). It emits BOTH a ``.md`` and a simple
self-contained ``.html`` (no markdown library).
"""

from __future__ import annotations

import html
import logging
from pathlib import Path

from v2.self_evolve.versioning import read_path_log, read_version

logger = logging.getLogger(__name__)

#: The baseline version id and the per-round id prefix (mirrors the loop).
_BASELINE_ID = "v0"


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _fmt_diff(x) -> str:
    """An A/B-vs-random diff (a forward-return gap) as signed percentage points."""
    if x is None:
        return "—"
    try:
        return f"{float(x) * 100:+.2f}pp"
    except (TypeError, ValueError):
        return "—"


def _fmt_t(x) -> str:
    """A t-stat to one decimal, signed (``—`` if None / unparseable)."""
    if x is None:
        return "—"
    try:
        return f"{float(x):+.2f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_pct(x) -> str:
    """A return/alpha as a signed percentage, e.g. ``+3.00%`` (``—`` if None)."""
    if x is None:
        return "—"
    try:
        return f"{float(x) * 100:+.2f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_int(x) -> str:
    """A non-negative count (``—`` if None / unparseable)."""
    if x is None:
        return "—"
    try:
        return str(int(x))
    except (TypeError, ValueError):
        return "—"


def _kept_mark(kept) -> str:
    """``✓ kept`` / ``rolled-back`` from a path-log ``kept`` flag."""
    return "✓ kept" if kept else "rolled-back"


# ---------------------------------------------------------------------------
# Store reads
# ---------------------------------------------------------------------------


def _val_of(base_dir, v_id: str) -> dict:
    """The ``val_metrics`` dict for ``v_id`` (``{}`` if absent — best-effort)."""
    rec = read_version(base_dir, v_id)
    val = rec.get("val_metrics") if isinstance(rec, dict) else None
    return val if isinstance(val, dict) else {}


def _last_kept_id(path_log: list[dict]) -> str:
    """The id of the LAST KEPT version, falling back to ``v0``.

    Walks the path log forward; the most recent entry with a truthy ``kept`` wins.
    A run where nothing past v0 was kept (or an empty log) yields ``v0``.
    """
    last = _BASELINE_ID
    for entry in path_log:
        if entry.get("kept"):
            vid = entry.get("v_id")
            if vid:
                last = vid
    return last


# ---------------------------------------------------------------------------
# Rendering — sections (list-of-lines, like the eval report)
# ---------------------------------------------------------------------------


def _render_path_table(base_dir, path_log: list[dict]) -> list[str]:
    """The optimization path: per-round v_id, val diff/n_fired/t, kept, hypothesis.

    Reads each round's val numbers from its ``version.json`` (NOT the path log,
    whose ``val_sharpe`` is ``None`` for scanner metrics).
    """
    lines = ["## Optimization path", ""]
    lines.append("Per round: validation A/B-vs-random `diff` (vs a seeded random " "same-universe baseline), `n_fired`, `t_stat`, kept/rolled-back, and the " "hypothesis. Validation `diff` is a SEARCH signal, not proven edge.")
    lines.append("")
    lines.append("| Version | val diff | n_fired | t_stat | Outcome | Hypothesis |")
    lines.append("|---|---|---|---|---|---|")
    for entry in path_log:
        v_id = entry.get("v_id", "?")
        val = _val_of(base_dir, v_id)
        cells = [
            str(v_id),
            _fmt_diff(val.get("diff")),
            _fmt_int(val.get("n_fired")),
            _fmt_t(val.get("t_stat")),
            _kept_mark(entry.get("kept")),
            str(entry.get("hypothesis", "") or "—"),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    if not path_log:
        lines.append("| _no versions recorded_ | — | — | — | — | — |")
    lines.append("")
    return lines


def _render_retained_config(base_dir, path_log: list[dict]) -> list[str]:
    """The retained-best config = the LAST KEPT version's config (fall back to v0)."""
    best_id = _last_kept_id(path_log)
    rec = read_version(base_dir, best_id)
    cfg = rec.get("config") if isinstance(rec, dict) else None
    cfg = cfg if isinstance(cfg, dict) else {}

    lines = ["## Retained config", ""]
    lines.append(f"The retained-best is **{best_id}** (the last kept version; the " "`v0` baseline if nothing improved). The scanner kernel is FIXED — " "`event_weight=1.0`, `quant_weight=0.0` — so only thresholds, per-detector " "severity multipliers, and `top_n` move.")
    lines.append("")

    detectors = cfg.get("detectors")
    if isinstance(detectors, dict) and detectors:
        lines.append("**Detector thresholds**")
        lines.append("")
        lines.append("| Detector | Params |")
        lines.append("|---|---|")
        for name in sorted(detectors):
            params = detectors[name]
            if isinstance(params, dict):
                params_str = ", ".join(f"{k}={params[k]}" for k in sorted(params))
            else:
                params_str = str(params)
            lines.append(f"| {name} | {params_str} |")
        lines.append("")

    sev = cfg.get("severity_mult")
    if isinstance(sev, dict) and sev:
        pairs = ", ".join(f"{k}={sev[k]}" for k in sorted(sev))
        lines.append(f"**severity_mult:** {pairs}")
        lines.append("")

    if "top_n" in cfg:
        lines.append(f"**top_n:** {cfg.get('top_n')}")
        lines.append("")

    if not cfg:
        lines.append("_no config could be reconstructed from the store_")
        lines.append("")
    return lines


def _render_test_verdict(test_metrics: dict | None) -> list[str]:
    """The single post-loop held-out TEST read (``diff`` / ``t_stat`` / ``n_fired`` / ``alpha_5d``)."""
    lines = ["## Held-out TEST verdict", ""]
    lines.append("The retained-best config scored ONCE on the held-out `test` sample " "(read exactly once, post-loop — never inside the search loop).")
    lines.append("")
    if not test_metrics:
        lines.append("_n/a — no test metrics supplied_")
        lines.append("")
        return lines
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| diff (A/B vs random) | {_fmt_diff(test_metrics.get('diff'))} |")
    lines.append(f"| t_stat | {_fmt_t(test_metrics.get('t_stat'))} |")
    lines.append(f"| n_fired | {_fmt_int(test_metrics.get('n_fired'))} |")
    lines.append(f"| alpha_5d (vs SPY) | {_fmt_pct(test_metrics.get('alpha_5d'))} |")
    lines.append("")
    return lines


def _render_caveats() -> list[str]:
    """The honest-caveat block — REQUIRED framing (mirrors the spec)."""
    return [
        "## Honest caveats",
        "",
        "- **Validation improvement is NOT proven edge.** A higher val `diff` means " "the search found a config that screened the regimes it SAW better than " "random — that is a search signal, not a verdict.",
        "- **The held-out TEST is a single read.** One number on one held-out span " "is weak evidence; it can be lucky. It bounds, but does not confirm, the edge.",
        "- **Three regimes is thin.** train+val span only bear/bull/choppy windows; " "a config tuned across three regimes can still fail to generalize.",
        "- **Self-evolution does not create edge.** It optimizes WITHIN the bounded " "threshold space; if no threshold setting screens better than chance, the " "loop cannot manufacture one.",
        "- **The LIVE scanner forward-test is the real judge.** Treat this report " "as a search summary; only the live forward-test verdicts an edge.",
        "",
    ]


# ---------------------------------------------------------------------------
# render / write
# ---------------------------------------------------------------------------


def render_report(base_dir, *, test_metrics: dict | None, generated_at: str | None = None) -> str:
    """Render the complete markdown run report from the store + the test read.

    Sections, in order: title + intro, Optimization path, Retained config,
    Held-out TEST verdict, Honest caveats. Best-effort: never raises on a
    partially-populated store.
    """
    path_log = read_path_log(base_dir)

    lines: list[str] = []
    lines.append("# Scanner self-evolve — run report")
    lines.append("")
    lines.append("Self-evolve tuned the price-only scanner's detector thresholds against " "an A/B-vs-random forward-return `diff` on **train+val**, then read the " "held-out **test** sample exactly once. The fixed kernel " "(`event_weight=1.0`, `quant_weight=0.0`) is never touched. " f"Generated at: {generated_at or '(pending)'}.")
    lines.append("")

    lines.extend(_render_path_table(base_dir, path_log))
    lines.extend(_render_retained_config(base_dir, path_log))
    lines.extend(_render_test_verdict(test_metrics))
    lines.extend(_render_caveats())

    return "\n".join(lines).rstrip() + "\n"


def _md_to_html(md_text: str) -> str:
    """Wrap rendered markdown in a minimal self-contained HTML page.

    No markdown library: the markdown is escaped and dropped inside a styled
    ``<pre>`` so every character (including the TEST fitness numbers) renders
    verbatim and the file is viewable standalone in a browser.
    """
    escaped = html.escape(md_text)
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        "<title>Scanner self-evolve — run report</title>\n"
        "<style>\n"
        "body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; "
        "max-width: 50rem; margin: 2rem auto; padding: 0 1rem; }\n"
        "pre { white-space: pre-wrap; word-wrap: break-word; "
        "background: #f6f8fa; padding: 1rem; border-radius: 6px; "
        "font-family: ui-monospace, SFMono-Regular, Menlo, monospace; "
        "font-size: 0.9rem; line-height: 1.5; }\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        f"<pre>{escaped}</pre>\n"
        "</body>\n"
        "</html>\n"
    )


def write_report(
    base_dir,
    *,
    test_metrics: dict | None,
    generated_at: str | None = None,
    out_dir=None,
) -> tuple[Path, Path]:
    """Render the run report and write both a ``.md`` and a ``.html`` file.

    Reads the version store under ``base_dir``; writes to ``out_dir`` (defaults
    to ``base_dir``) as ``scanner_evolve_report.md`` + ``.html``. The TEST fitness
    numbers appear in BOTH outputs. Returns ``(md_path, html_path)``. Pure
    rendering — ``generated_at`` is supplied by the caller (this never calls
    ``datetime.now()``).
    """
    out_dir = Path(out_dir) if out_dir is not None else Path(base_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    md_text = render_report(base_dir, test_metrics=test_metrics, generated_at=generated_at)
    html_text = _md_to_html(md_text)

    md_path = out_dir / "scanner_evolve_report.md"
    html_path = out_dir / "scanner_evolve_report.html"
    md_path.write_text(md_text, encoding="utf-8")
    html_path.write_text(html_text, encoding="utf-8")

    logger.info("wrote scanner-evolve run report: %s + %s", md_path, html_path)
    return md_path, html_path
