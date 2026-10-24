"""argparse entrypoint for ``python -m v2.backtesting.run``.

Decouples argument parsing from ``engine.run_backtest`` so the engine
stays callable from notebooks / scripts without going through stdin.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from v2.backtesting.engine import run_backtest


_MIN_FORWARD_DAYS = 5  # CLI guard: don't backtest dates so recent that
                       # the longest forward window has zero data.


def _parse_iso_date(s: str) -> str:
    """Validate a YYYY-MM-DD string and return it unchanged."""
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"date must be YYYY-MM-DD, got {s!r}"
        )
    return s


def _parse_tickers(s: str) -> list[str]:
    """Comma- or space-separated ticker list → uppercased deduped list."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in s.replace(",", " ").split():
        t = raw.strip().upper()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _parse_weights(s: str) -> dict:
    """Inline JSON for ScannerWeights (e.g. enabled_detectors, mults)."""
    try:
        obj = json.loads(s)
    except json.JSONDecodeError as e:
        raise argparse.ArgumentTypeError(f"--weights must be valid JSON: {e}")
    if not isinstance(obj, dict):
        raise argparse.ArgumentTypeError(f"--weights must be a JSON object, got {type(obj).__name__}")
    return obj


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m v2.backtesting.run",
        description=(
            "Replay the v2 scanner over a historical date range and write "
            "per-entry forward returns (1d/5d/20d/63d) + benchmark-relative "
            "alpha to CSV. NOTE: target_price_change detector is skipped "
            "(needs forward-only DB snapshots); earnings_upcoming returns "
            "no triggers in v1 (no historical calendar pre-staging). "
            "Universe is the CURRENT snapshot — backtest is subject to "
            "survivorship bias."
        ),
    )

    universe_group = p.add_argument_group("universe")
    universe_group.add_argument(
        "--universe",
        default="nasdaq100",
        choices=["sp500", "nasdaq100", "nasdaq100_sp500", "russell3000", "all_us", "custom"],
        help="Universe kind (default: nasdaq100). Use 'custom' with --tickers for a manual list.",
    )
    universe_group.add_argument(
        "--tickers",
        type=_parse_tickers,
        default=None,
        help="Required when --universe=custom. Comma- or space-separated.",
    )

    p.add_argument(
        "--weights",
        type=_parse_weights,
        default=None,
        help=(
            "Inline JSON for ScannerWeights — e.g. "
            "'{\"enabled_detectors\":[\"earnings_event\",\"bollinger_squeeze\"]}'. "
            "Omit for the default detector set (everything except target_price_change)."
        ),
    )

    p.add_argument("--start", required=True, type=_parse_iso_date,
                   help="Backtest start date (YYYY-MM-DD).")
    p.add_argument("--end", required=True, type=_parse_iso_date,
                   help="Backtest end date (YYYY-MM-DD), inclusive.")
    p.add_argument("--top-n", type=int, default=20,
                   help="Per-day watchlist size (default: 20).")
    p.add_argument("--max-days", type=int, default=None,
                   help="Stop after this many trading days (smoke-run safety).")
    p.add_argument("--output", type=Path, default=None,
                   help="CSV output path (default: ./backtest_<universe>_<start>_<end>.csv).")
    p.add_argument("--benchmark", default="SPY",
                   help="Benchmark ticker for alpha computation (default: SPY).")
    p.add_argument("--no-quant-signals", action="store_true",
                   help="Disable the 5 quant signals (momentum/value/quality/"
                        "earnings_quality/technical) — composite_score becomes "
                        "event_score only. Use for ablation studies comparing "
                        "scanner with vs without quant.")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="DEBUG-level logging.")

    return p


def main(argv: list[str] | None = None) -> int:
    # Mirror the backend's startup contract: load .env so EODHD_API_KEY /
    # FINNHUB_API_KEY etc. are available. Backend's uvicorn process loads
    # this via app/backend/main.py; the CLI needs to do it itself or
    # provider clients fail with 401.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.universe == "custom" and not args.tickers:
        parser.error("--universe=custom requires --tickers")

    # Guard against requesting a backtest so recent that forward windows
    # have no data. Lets the user fail fast with a clear message rather
    # than silently producing all-None forward columns.
    today = date.today()
    end_d = datetime.strptime(args.end, "%Y-%m-%d").date()
    if end_d > today - timedelta(days=_MIN_FORWARD_DAYS):
        cutoff = (today - timedelta(days=_MIN_FORWARD_DAYS)).isoformat()
        parser.error(
            f"--end {args.end} is too close to today ({today.isoformat()}); "
            f"forward returns won't be computable. Use --end ≤ {cutoff}."
        )
    if args.start >= args.end:
        parser.error(f"--start {args.start} must be before --end {args.end}")

    output_path = args.output
    if output_path is None:
        slug = args.universe if args.universe != "custom" else "custom"
        output_path = Path(f"backtest_{slug}_{args.start}_{args.end}.csv")

    n = run_backtest(
        universe_kind=args.universe,
        universe_tickers=args.tickers,
        weights_payload=args.weights,
        start_date=args.start,
        end_date=args.end,
        top_n=args.top_n,
        output_path=output_path,
        benchmark_ticker=args.benchmark,
        max_days=args.max_days,
        use_quant_signals=not args.no_quant_signals,
    )
    return 0 if n >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
