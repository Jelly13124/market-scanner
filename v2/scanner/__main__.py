"""Smoke-test the daily market scanner end-to-end.

Usage:
    python -m v2.scanner                          # SP500 seed (61 tickers), top 20, today
    python -m v2.scanner --universe sp500 --top 20
    python -m v2.scanner --end-date 2026-05-12
    python -m v2.scanner --universe custom --tickers AAPL,MSFT,NVDA,TSLA,META

Requires ``FINANCIAL_DATASETS_API_KEY`` in the environment (loaded from .env).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date

from dotenv import load_dotenv

# Windows console defaults to cp1252; force UTF-8 so colored / unicode output
# works in PowerShell + Windows Terminal.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

from v2.scanner.runner import ScanProgress, run_scan
from v2.scanner.universes import load_universe

# ANSI colors — Windows Terminal / modern shells support these.
GREEN = "\033[32m"
RED = "\033[31m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
DIM = "\033[90m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _fmt_direction(direction: str) -> str:
    if direction == "bullish":
        return f"{GREEN}↑ bull{RESET}"
    if direction == "bearish":
        return f"{RED}↓ bear{RESET}"
    return f"{DIM}→ neut{RESET}"


def _fmt_triggers(triggers: list[dict]) -> str:
    short = {
        "earnings_event": "EARN",
        "earnings_surprise": "EARN",   # legacy
        "earnings_upcoming": "EARN",   # legacy
        "insider_cluster": "INSDR",
        "price_volume_anomaly": "VOL",
        "news_sentiment_shift": "NEWS",
        "intraday_move": "IDAY",
        "analyst_rating": "ANLY",
        "target_price_change": "TGT",
        "bollinger_squeeze": "SQZ",
        "obv_divergence": "OBV",
    }
    bits: list[str] = []
    for t in triggers:
        label = short.get(t["detector"], t["detector"][:4].upper())
        z = t["severity_z"]
        color = GREEN if z > 0 else RED
        bits.append(f"{color}{label}({z:+.1f}){RESET}")
    return " ".join(bits)


def main() -> int:
    parser = argparse.ArgumentParser(description="v2 scanner smoke test")
    parser.add_argument(
        "--universe", default="nasdaq100_sp500",
        choices=["sp500", "nasdaq100", "nasdaq100_sp500", "russell3000", "all_us", "custom"],
    )
    parser.add_argument("--tickers", help="Comma-separated tickers for --universe custom")
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument(
        "--provider", choices=["fd", "finnhub", "eodhd", "hybrid"], default=None,
        help="Override SCANNER_DATA_PROVIDER. 'hybrid' = EODHD (prices+news) + Finnhub (insider+earnings).",
    )
    parser.add_argument("--workers", type=int, default=None,
                        help="Default: 16 for fd, 4 for finnhub")
    args = parser.parse_args()

    load_dotenv()

    # Apply --provider override before factories are touched.
    if args.provider:
        os.environ["SCANNER_DATA_PROVIDER"] = args.provider

    from v2.data.factory import get_default_provider, get_provider_factory, recommend_max_workers
    active_provider = get_default_provider()
    if active_provider == "fd" and not os.environ.get("FINANCIAL_DATASETS_API_KEY"):
        print(f"{RED}ERROR: FINANCIAL_DATASETS_API_KEY not set (looked in .env){RESET}", file=sys.stderr)
        return 2
    if active_provider == "finnhub" and not os.environ.get("FINNHUB_API_KEY"):
        print(f"{RED}ERROR: FINNHUB_API_KEY not set (looked in .env){RESET}", file=sys.stderr)
        return 2
    if active_provider == "eodhd" and not os.environ.get("EODHD_API_KEY"):
        print(f"{RED}ERROR: EODHD_API_KEY not set (looked in .env){RESET}", file=sys.stderr)
        return 2
    if active_provider == "hybrid":
        missing = [k for k in ("EODHD_API_KEY", "FINNHUB_API_KEY") if not os.environ.get(k)]
        if missing:
            print(f"{RED}ERROR: hybrid provider needs both {missing} set in .env{RESET}", file=sys.stderr)
            return 2

    workers = args.workers if args.workers is not None else recommend_max_workers()

    custom = None
    if args.tickers:
        custom = [t.strip() for t in args.tickers.split(",") if t.strip()]
    tickers = load_universe(args.universe, custom=custom)

    print(f"{BOLD}Scanning {len(tickers)} tickers from '{args.universe}' for {args.end_date}{RESET}")
    print(f"  Provider: {CYAN}{active_provider}{RESET}  Workers: {workers}  Top-N: {args.top}")
    print()

    last_pct = -10

    def progress(p: ScanProgress) -> None:
        nonlocal last_pct
        pct = int(100 * p.processed / max(p.total, 1))
        if pct - last_pct >= 10 or pct >= 100:
            eta = f"ETA {p.eta_seconds:.0f}s" if p.eta_seconds and p.eta_seconds > 0 else ""
            print(
                f"  [{pct:>3}%] {p.processed}/{p.total}  "
                f"triggered={p.triggered}  skipped={p.skipped}  errors={p.errors}  {eta}"
            )
            last_pct = pct

    # Match production ScannerService behavior — include the 5 quant
    # signals so composite_score uses the configured event/quant split.
    from v2.signals import ALL_SIGNALS

    started = time.monotonic()
    result = run_scan(
        tickers=tickers,
        end_date=args.end_date,
        top_n=args.top,
        max_workers=workers,
        progress_cb=progress,
        progress_every=5,
        quant_signals=[cls() for cls in ALL_SIGNALS],
    )
    elapsed = time.monotonic() - started

    print()
    print(f"{BOLD}Top {len(result)} watchlist for {args.end_date}:{RESET}")
    print()
    print(f"  {'#':>3}  {'Ticker':<8} {'Score':>5}  {'Dir':<8}  Triggers")
    print(f"  {'-' * 74}")
    for e in result:
        print(
            f"  {e.rank:>3}  {CYAN}{e.ticker:<8}{RESET} "
            f"{e.composite_score:>5.1f}  {_fmt_direction(e.direction)}  "
            f"{_fmt_triggers(e.triggers)}"
        )

    print()
    print(f"  Completed in {elapsed:.1f}s ({len(result)}/{len(tickers)} tickers triggered)")
    if not result:
        print(
            f"  {YELLOW}No tickers had events on {args.end_date}. "
            f"Try a different --end-date or universe.{RESET}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
