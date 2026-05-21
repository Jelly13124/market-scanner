"""A/B backtest: scanner-picked tickers vs random tickers, both routed
through the full agent pipeline.

The experiment validates project-scanner-design-intent: scanner is an
LLM-cost pre-filter, not a directional predictor. The win condition is
"PM decisions on scanner-flagged tickers produce better realized PnL
than PM decisions on randomly sampled tickers, same agents same day".

For each trading day in the window:
  A) run_pipeline(top_n=N) → scanner picks → agent pipeline → decisions
  B) random.sample(universe − A_tickers, N) → agent pipeline with EMPTY
     scanner_context → decisions

For each PM decision in both groups, compute forward 5d/20d PnL using
the v2 hybrid client's price data. Decisions are mark-to-market:

  BUY  qty Q  →  PnL_Nd = +Q × (price_t+N / price_t − 1)
  SHORT qty Q →  PnL_Nd = −Q × same
  HOLD       →  PnL_Nd = 0  (no position opened)

Outputs:
  outputs/ab_backtest_<start>_<end>.csv  — one row per PM decision
  outputs/ab_backtest_<start>_<end>_summary.txt — aggregated A vs B
"""

from __future__ import annotations

import argparse
import csv
import logging
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# scripts/ runs with the script directory on sys.path, not the repo root —
# add the repo root so ``from v2...`` and ``from src...`` resolve.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Run one A/B pair for a single scan date
# ----------------------------------------------------------------------


def _run_one_day(
    *,
    scan_date: str,
    universe_kind: str,
    top_n: int,
    template: str,
    model_name: str,
    model_provider: str,
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Returns a list of decision rows (both groups combined) for one day.

    Each row has: scan_date, group, ticker, action, quantity, confidence,
    scanner_triggered_detectors (A only), pipeline_duration_seconds.
    Forward PnL is computed in a separate pass once all days are done.
    """
    from v2.pipeline.orchestrator import run_agents_only, run_pipeline

    rows: list[dict[str, Any]] = []

    # ---- Group A: scanner → agents ----
    logger.info("[%s] Group A: scanner pipeline, top_n=%d", scan_date, top_n)
    t0 = time.monotonic()
    try:
        result_a = run_pipeline(
            scan_date=scan_date,
            universe=universe_kind,
            top_n=top_n,
            template=template,
            model_name=model_name,
            model_provider=model_provider,
            persist=False,
        )
    except Exception as e:
        logger.exception("[%s] Group A failed: %s", scan_date, e)
        return rows
    dur_a = time.monotonic() - t0

    a_tickers = list((result_a.agent_decisions or {}).keys())
    a_scanner_ctx_by_ticker: dict[str, list[str]] = {}
    for entry in (result_a.watchlist or []):
        t = entry.get("ticker")
        if t:
            triggers = [tr.get("detector") for tr in (entry.get("triggers") or [])
                        if tr.get("triggered") and tr.get("detector")]
            a_scanner_ctx_by_ticker[t] = triggers

    for ticker, decision in (result_a.agent_decisions or {}).items():
        rows.append({
            "scan_date": scan_date,
            "group": "A",
            "ticker": ticker,
            "action": decision.get("action"),
            "quantity": decision.get("quantity"),
            "confidence": decision.get("confidence"),
            "triggered_detectors": ",".join(a_scanner_ctx_by_ticker.get(ticker, [])),
            "pipeline_duration_s": round(dur_a, 1),
        })
    logger.info("[%s] Group A done: %d decisions in %.1fs",
                scan_date, len(rows), dur_a)

    # ---- Group B: random tickers, empty scanner_context ----
    from v2.scanner.universes.loader import load_universe

    universe = load_universe(universe_kind)
    # Exclude A's picks so the groups are disjoint per-day — otherwise
    # they could overlap by chance, muddling the comparison.
    pool = [t for t in universe if t not in a_tickers]
    if len(pool) < top_n:
        logger.warning("[%s] Universe too small after excluding A's picks", scan_date)
        return rows
    b_tickers = rng.sample(pool, top_n)
    logger.info("[%s] Group B: random pipeline on %s", scan_date, b_tickers)

    t0 = time.monotonic()
    try:
        result_b = run_agents_only(
            tickers=b_tickers,
            scan_date=scan_date,
            scanner_context={},  # Empty — scanner_signal_agent abstains.
            template=template,
            model_name=model_name,
            model_provider=model_provider,
        )
    except Exception as e:
        logger.exception("[%s] Group B failed: %s", scan_date, e)
        return rows
    dur_b = time.monotonic() - t0

    b_rows_added = 0
    for ticker, decision in (result_b["decisions"] or {}).items():
        rows.append({
            "scan_date": scan_date,
            "group": "B",
            "ticker": ticker,
            "action": decision.get("action"),
            "quantity": decision.get("quantity"),
            "confidence": decision.get("confidence"),
            "triggered_detectors": "",
            "pipeline_duration_s": round(dur_b, 1),
        })
        b_rows_added += 1
    logger.info("[%s] Group B done: %d decisions in %.1fs",
                scan_date, b_rows_added, dur_b)
    return rows


# ----------------------------------------------------------------------
# Forward PnL computation (post-pipeline pass)
# ----------------------------------------------------------------------


def _attach_forward_pnl(
    rows: list[dict[str, Any]],
    windows: tuple[int, ...],
    cost_bp: float = 0.0,
) -> None:
    """Mutate each row in place adding ``entry_price``, ``price_{N}d``,
    ``pnl_{N}d`` for each window N. Uses the same v2 hybrid client the
    scanner uses so prices are consistent with the rest of the system.

    Skips rows whose action is HOLD (no position, no PnL).

    ``cost_bp`` deducts a flat round-trip transaction cost in basis points
    from each non-HOLD decision (10bp ≈ realistic combined slippage +
    commission + spread on a NDX100-grade name). HOLD entries stay at 0.
    """
    from src.tools.api import get_prices

    # Pre-compute forward-date lookups in a single price fetch per ticker
    # rather than N fetches per ticker. We need prices from scan_date
    # through scan_date + max(windows)+5 calendar days to cover any
    # weekends/holidays.
    max_window = max(windows)
    by_ticker_scan: dict[tuple[str, str], list[Any]] = {}
    for r in rows:
        key = (r["ticker"], r["scan_date"])
        if key in by_ticker_scan:
            continue
        end_dt = datetime.strptime(r["scan_date"], "%Y-%m-%d")
        from datetime import timedelta
        forward_end = (end_dt + timedelta(days=max_window + 14)).date().isoformat()
        try:
            prices = get_prices(r["ticker"], r["scan_date"], forward_end)
        except Exception as e:
            logger.warning("get_prices %s @ %s failed: %s",
                           r["ticker"], r["scan_date"], e)
            prices = []
        by_ticker_scan[key] = prices

    for r in rows:
        action = (r.get("action") or "").lower()
        if action not in ("buy", "short", "sell", "cover"):
            r["entry_price"] = None
            for w in windows:
                r[f"price_{w}d"] = None
                r[f"pnl_{w}d"] = 0.0
            continue

        prices = by_ticker_scan.get((r["ticker"], r["scan_date"]), [])
        if not prices:
            r["entry_price"] = None
            for w in windows:
                r[f"price_{w}d"] = None
                r[f"pnl_{w}d"] = None
            continue

        prices_sorted = sorted(prices, key=lambda p: p.time[:10])
        # Entry = first close on/after scan_date.
        entry_idx = None
        for i, p in enumerate(prices_sorted):
            if p.time[:10] >= r["scan_date"]:
                entry_idx = i
                break
        if entry_idx is None:
            r["entry_price"] = None
            for w in windows:
                r[f"price_{w}d"] = None
                r[f"pnl_{w}d"] = None
            continue

        entry_price = float(prices_sorted[entry_idx].close)
        r["entry_price"] = entry_price

        qty = float(r.get("quantity") or 0)
        for w in windows:
            target_idx = entry_idx + w
            if target_idx >= len(prices_sorted):
                r[f"price_{w}d"] = None
                r[f"pnl_{w}d"] = None
                continue
            future_price = float(prices_sorted[target_idx].close)
            r[f"price_{w}d"] = future_price
            ret = (future_price / entry_price) - 1.0
            # Direction sign by action.
            sign = +1.0 if action in ("buy", "cover") else -1.0
            gross_pnl = qty * sign * ret * entry_price
            cost = (cost_bp / 10_000.0) * qty * entry_price
            r[f"pnl_{w}d"] = round(gross_pnl - cost, 4)


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start", required=True, help="YYYY-MM-DD inclusive")
    p.add_argument("--end", required=True, help="YYYY-MM-DD inclusive")
    p.add_argument("--universe", default="nasdaq100")
    p.add_argument("--top-n", type=int, default=3)
    p.add_argument("--template", default="balanced")
    p.add_argument("--model-name", default="deepseek-chat")
    p.add_argument("--model-provider", default="DeepSeek")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--windows", default="5,20",
                   help="Comma-separated forward-window trading days for PnL.")
    p.add_argument("--cost-bp", type=float, default=10.0,
                   help="Round-trip transaction cost in basis points per "
                        "non-HOLD decision (default: 10 = 0.10%%; covers "
                        "slippage + commission + spread). Set 0 to disable.")
    p.add_argument("--out", type=Path, default=None,
                   help="CSV output path (default: outputs/ab_backtest_<start>_<end>.csv)")
    return p.parse_args()


def main() -> int:
    # Load .env so EODHD / Finnhub / DeepSeek keys are available.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Quiet noisy third-party loggers; we want our progress lines to dominate.
    for name in ("urllib3", "httpx", "yfinance"):
        logging.getLogger(name).setLevel(logging.WARNING)

    args = _parse_args()
    windows = tuple(int(w.strip()) for w in args.windows.split(",") if w.strip())
    rng = random.Random(args.seed)

    out_path = args.out or Path(f"outputs/ab_backtest_{args.start}_{args.end}.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Trading calendar — only iterate days the scanner can actually scan.
    from v2.backtesting.trading_calendar import trading_days_between
    from v2.data.factory import get_provider_factory

    provider_factory = get_provider_factory()
    client = provider_factory()
    try:
        trading_days = trading_days_between(
            client, start_date=args.start, end_date=args.end,
        )
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    if not trading_days:
        print(f"ERROR: no trading days in [{args.start}, {args.end}]", file=sys.stderr)
        return 1

    print(f"A/B backtest plan: {len(trading_days)} trading days "
          f"({trading_days[0]} → {trading_days[-1]}), top_n={args.top_n}, "
          f"template={args.template}, model={args.model_name}")
    print(f"Output → {out_path}")

    all_rows: list[dict[str, Any]] = []
    t_start = time.monotonic()
    for i, day in enumerate(trading_days, 1):
        print(f"\n--- [{i}/{len(trading_days)}] {day} ---")
        try:
            day_rows = _run_one_day(
                scan_date=day,
                universe_kind=args.universe,
                top_n=args.top_n,
                template=args.template,
                model_name=args.model_name,
                model_provider=args.model_provider,
                rng=rng,
            )
        except KeyboardInterrupt:
            print("Interrupted — writing partial results")
            break
        except Exception as e:
            logger.exception("[%s] day failed: %s", day, e)
            day_rows = []
        all_rows.extend(day_rows)
        # Atomic per-day flush so we don't lose progress on crash.
        _write_csv(all_rows, out_path, windows)
    print(f"\nAll {len(trading_days)} days done in {time.monotonic() - t_start:.0f}s")
    print(f"Computing forward PnL for {len(all_rows)} decisions (cost={args.cost_bp:g} bp)...")
    _attach_forward_pnl(all_rows, windows=windows, cost_bp=args.cost_bp)
    _write_csv(all_rows, out_path, windows)
    print(f"Wrote {out_path} ({len(all_rows)} rows)")
    return 0


def _write_csv(rows: list[dict[str, Any]], path: Path, windows: tuple[int, ...]) -> None:
    if not rows:
        return
    fixed_cols = [
        "scan_date", "group", "ticker", "action", "quantity", "confidence",
        "triggered_detectors", "entry_price",
    ]
    forward_cols = []
    for w in windows:
        forward_cols.extend([f"price_{w}d", f"pnl_{w}d"])
    fixed_cols.extend(forward_cols)
    fixed_cols.append("pipeline_duration_s")
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fixed_cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    sys.exit(main())
