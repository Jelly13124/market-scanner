"""CLI entrypoint: python -m src.research --ticker NVDA.

Phase 1 prints a summary to stdout. Phase 3 will add --output html and
--email flags.
"""

from __future__ import annotations

import argparse
import logging
import sys

from src.research.models import ResearchRequest
from src.research.pipeline import run_research


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m src.research",
                                description="Run per-stock research pipeline.")
    p.add_argument("--ticker", required=True, help="Ticker symbol, e.g. NVDA")
    p.add_argument("--holding-status",
                   choices=["holding", "watching", "considering_buy",
                            "considering_short"],
                   default="watching")
    p.add_argument("--position-pct", type=float, default=0.05,
                   help="Target position size, fraction (default: 0.05)")
    p.add_argument("--risk",
                   choices=["conservative", "moderate", "aggressive"],
                   default="moderate")
    p.add_argument("--goal",
                   choices=["new_entry", "hold_review", "exit_decision",
                            "general_research"],
                   default="general_research")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def _print_summary(state) -> None:
    plan = state["strategy"]
    backtest = state["backtest_summary"]
    req = state["request"]

    print()
    print("=" * 72)
    print(f"  {req.ticker} - research report")
    print("=" * 72)
    print(f"  Holding status: {req.holding_status} | "
          f"Risk: {req.risk_tolerance} | Goal: {req.report_goal}")
    print()
    print("-" * 72)
    print(f"  TRADE PLAN: {plan.direction.upper()}")
    print("-" * 72)
    if plan.direction == "stand_aside":
        print(f"  No actionable trade. Confidence: {plan.confidence}/100")
        print(f"  Rationale: {plan.rationale}")
    else:
        print(f"  Entry:  ${plan.entry_price:.2f}")
        print(f"  Target: ${plan.target_price:.2f}")
        print(f"  Stop:   ${plan.stop_price:.2f}")
        print(f"  Horizon: {plan.horizon_days} days")
        print(f"  Sizing: {plan.sizing_pct * 100:.2f}% of portfolio")
        print(f"  Confidence: {plan.confidence}/100")
        print(f"  Rationale: {plan.rationale}")

    print()
    print("-" * 72)
    print(f"  DETECTOR BACKTEST ({backtest.sample_quality})")
    print("-" * 72)
    print(f"  Matches found: {backtest.matches_found}")
    if backtest.win_rate is not None:
        print(f"  Win rate: {backtest.win_rate * 100:.1f}%")
        print(f"  Avg PnL: {(backtest.avg_pnl_pct or 0) * 100:+.2f}%")
        print(f"  Max drawdown: {(backtest.max_drawdown_pct or 0) * 100:+.2f}%")
    if backtest.caveat:
        print(f"  Caveat: {backtest.caveat}")

    print()
    print("-" * 72)
    print("  REPORT")
    print("-" * 72)
    print(state["report_markdown"])
    print()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    request = ResearchRequest(
        ticker=args.ticker.upper(),
        holding_status=args.holding_status,
        target_position_pct=args.position_pct,
        risk_tolerance=args.risk,
        report_goal=args.goal,
        use_personas=False,  # Phase 1 has no router
        scanner_context=None,
    )
    state = run_research(request)
    _print_summary(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
