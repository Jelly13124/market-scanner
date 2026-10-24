"""CLI entrypoint for the SOP-driven Analyze pipeline.

Usage:
    python -m src.research --ticker NVDA --objective medium_term --use-personas

Writes the rendered HTML report to a tempfile and prints the path.
Per-section completion summary + persona assignments + backtest verdict
are printed to stderr.
"""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from pathlib import Path

# Load .env so DEEPSEEK_API_KEY / EODHD_API_KEY etc. are available.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m src.research",
        description="Run the SOP-driven per-stock analyze pipeline.",
    )
    p.add_argument("--ticker", required=True, help="e.g. NVDA")
    p.add_argument(
        "--objective",
        choices=["target_price", "short_term", "medium_term",
                 "long_term", "earnings_review", "general_research"],
        default="general_research",
    )
    p.add_argument("--budget", type=float, default=None,
                   help="Position budget in USD (optional)")
    p.add_argument("--holds", action="store_true",
                   help="Mark that the user already holds this ticker")
    p.add_argument("--cost-basis", type=float, default=None,
                   help="Cost basis per share if --holds")
    p.add_argument(
        "--risk", choices=["conservative", "balanced", "aggressive"],
        default="balanced",
    )
    p.add_argument("--use-personas", action="store_true",
                   help="Enable persona router + persona-aware sections + debate")
    p.add_argument("--only", action="append", default=None,
                   help="Restrict to specific sections (repeatable). "
                        "Default: all 16 SOP sections.")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def _print_persona_box(assignments: dict | None) -> None:
    if not assignments:
        return
    print("=" * 72, file=sys.stderr)
    print("  PERSONA ASSIGNMENTS", file=sys.stderr)
    print("=" * 72, file=sys.stderr)
    for k in ("fundamentals", "valuation", "risk_position"):
        v = assignments.get(k)
        print(f"  {k:<24s} : {v if v else 'objective'}", file=sys.stderr)
    debate = assignments.get("debate") or []
    if isinstance(debate, list) and len(debate) == 2:
        print(f"  {'debate':<24s} : {debate[0]} vs {debate[1]}", file=sys.stderr)
    if assignments.get("_rationale"):
        print(f"  rationale: {assignments['_rationale']}", file=sys.stderr)


def _print_backtest_box(b) -> None:
    if b is None:
        return
    print("=" * 72, file=sys.stderr)
    print(f"  BACKTEST VERDICT - signal '{b.signal}'", file=sys.stderr)
    print("=" * 72, file=sys.stderr)
    print(f"  window: {b.window_start} -> {b.window_end}", file=sys.stderr)
    print(f"  occurrences: {b.n_signals}", file=sys.stderr)
    if b.win_rate_20d is not None:
        print(f"  win rate (20d): {b.win_rate_20d * 100:.0f}%", file=sys.stderr)
        print(f"  avg return (20d): {b.avg_return_20d * 100:+.2f}%", file=sys.stderr)
        if b.t_stat is not None:
            print(f"  t-stat: {b.t_stat:.2f}", file=sys.stderr)
    print(f"  verdict: {b.verdict}", file=sys.stderr)


def _print_sections_summary(sections: dict) -> None:
    print("=" * 72, file=sys.stderr)
    print("  SECTIONS", file=sys.stderr)
    print("=" * 72, file=sys.stderr)
    for name, payload in sections.items():
        if name.startswith("_"):
            continue
        mark = "+" if not payload.skipped else "."
        reason = f" ({payload.skip_reason})" if payload.skipped and payload.skip_reason else ""
        print(f"  {mark} {name}{reason}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Import here so unit tests can patch fetch_shared_data etc. before
    # the module-level singletons resolve.
    from src.research.models import AnalyzeRequest, SECTION_ORDER
    from src.research.sop_orchestrator import run_sop
    from src.research.html_render import render_sop

    included = set(args.only) if args.only else set(SECTION_ORDER)
    request = AnalyzeRequest(
        ticker=args.ticker.upper(),
        objective=args.objective,
        position_budget_usd=args.budget,
        already_holds=args.holds,
        cost_basis_usd=args.cost_basis,
        risk_tolerance=args.risk,
        use_personas=args.use_personas,
        included_sections=included,
    )

    print(f"Running SOP for {request.ticker} (objective={request.objective}, "
          f"sections={len(included)}, personas={request.use_personas})...",
          file=sys.stderr)

    report = run_sop(request)

    _print_persona_box(report.get("persona_assignments"))
    _print_backtest_box(report.get("backtest"))
    _print_sections_summary(report.get("sections", {}))

    # Render HTML and write to tempfile
    html = render_sop(report)
    report["rendered_html"] = html

    tmp = Path(tempfile.gettempdir()) / f"analyze_{request.ticker}.html"
    tmp.write_text(html, encoding="utf-8")
    print(str(tmp))  # stdout - the user-consumable result

    return 0


if __name__ == "__main__":
    sys.exit(main())
