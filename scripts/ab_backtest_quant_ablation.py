"""A/B backtest: scanner+agents WITH quant_signals vs WITHOUT.

Mirrors scripts/ab_backtest.py structure but BOTH groups go through the
full scanner→agent→PM pipeline. The only difference is the scanner's
``use_quant_signals`` flag:

  Group A (control)  → scanner runs with the 5 quant signals (current prod)
  Group B (treatment)→ scanner runs without them (event_score only)

Why this matters: Part 1's A/B already showed scanner→agent beats random
→agent in directional markets. But BOTH groups in Part 1 had quant on.
This script isolates whether quant_signals contribute at the agent layer
(by giving agents better-scored watchlists) or whether they're inert.

For each PM decision in both groups, compute forward PnL the same way
ab_backtest.py does. Output schema identical so the same downstream
summary tool works.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logger = logging.getLogger(__name__)


def _run_one_day(
    *,
    scan_date: str,
    universe_kind: str,
    top_n: int,
    template: str,
    model_name: str,
    model_provider: str,
) -> list[dict[str, Any]]:
    """One trading day, both groups. Returns list of decision rows."""
    from v2.pipeline.orchestrator import run_pipeline

    rows: list[dict[str, Any]] = []

    for group, use_quant in (("A", True), ("B", False)):
        logger.info("[%s] Group %s: scanner+agents, quant=%s",
                    scan_date, group, use_quant)
        t0 = time.monotonic()
        try:
            result = run_pipeline(
                scan_date=scan_date,
                universe=universe_kind,
                top_n=top_n,
                template=template,
                model_name=model_name,
                model_provider=model_provider,
                persist=False,
                use_quant_signals=use_quant,
            )
        except Exception as e:
            logger.exception("[%s] Group %s failed: %s", scan_date, group, e)
            continue
        dur = time.monotonic() - t0

        ctx_by_ticker: dict[str, list[str]] = {}
        for entry in (result.watchlist or []):
            t = entry.get("ticker")
            if t:
                triggers = [tr.get("detector") for tr in (entry.get("triggers") or [])
                            if tr.get("triggered") and tr.get("detector")]
                ctx_by_ticker[t] = triggers

        for ticker, decision in (result.agent_decisions or {}).items():
            rows.append({
                "scan_date": scan_date,
                "group": group,
                "ticker": ticker,
                "action": decision.get("action"),
                "quantity": decision.get("quantity"),
                "confidence": decision.get("confidence"),
                "triggered_detectors": ",".join(ctx_by_ticker.get(ticker, [])),
                "pipeline_duration_s": round(dur, 1),
            })
        logger.info("[%s] Group %s done: %d decisions in %.1fs",
                    scan_date, group, len(result.agent_decisions or {}), dur)
    return rows


def _attach_forward_pnl(
    rows: list[dict[str, Any]],
    windows: tuple[int, ...],
    cost_bp: float = 0.0,
) -> None:
    """In-place: add entry_price + price_{N}d + pnl_{N}d for each row.

    HOLD/SELL of non-existent positions → pnl = 0. Same convention as
    ab_backtest.py (so the same summary script works).

    ``cost_bp`` deducts a flat round-trip transaction cost in basis points
    from each non-HOLD decision (10bp ≈ realistic combined slippage +
    commission + spread).
    """
    from src.tools.api import get_prices

    max_window = max(windows)
    from datetime import timedelta
    cache: dict[tuple[str, str], list[Any]] = {}
    for r in rows:
        key = (r["ticker"], r["scan_date"])
        if key in cache:
            continue
        end_dt = datetime.strptime(r["scan_date"], "%Y-%m-%d")
        forward_end = (end_dt + timedelta(days=max_window + 14)).date().isoformat()
        try:
            cache[key] = get_prices(r["ticker"], r["scan_date"], forward_end)
        except Exception as e:
            logger.warning("get_prices %s @ %s failed: %s",
                           r["ticker"], r["scan_date"], e)
            cache[key] = []

    for r in rows:
        action = (r.get("action") or "").lower()
        if action not in ("buy", "short", "sell", "cover"):
            r["entry_price"] = None
            for w in windows:
                r[f"price_{w}d"] = None
                r[f"pnl_{w}d"] = 0.0
            continue

        prices = cache.get((r["ticker"], r["scan_date"]), [])
        if not prices:
            r["entry_price"] = None
            for w in windows:
                r[f"price_{w}d"] = None
                r[f"pnl_{w}d"] = None
            continue

        prices_sorted = sorted(prices, key=lambda p: p.time[:10])
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
            sign = +1.0 if action in ("buy", "cover") else -1.0
            gross_pnl = qty * sign * ret * entry_price
            cost = (cost_bp / 10_000.0) * qty * entry_price
            r[f"pnl_{w}d"] = round(gross_pnl - cost, 4)


def _write_csv(rows: list[dict[str, Any]], path: Path, windows: tuple[int, ...]) -> None:
    if not rows:
        return
    cols = ["scan_date", "group", "ticker", "action", "quantity", "confidence",
            "triggered_detectors", "entry_price"]
    for w in windows:
        cols.extend([f"price_{w}d", f"pnl_{w}d"])
    cols.append("pipeline_duration_s")
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start", required=True, help="YYYY-MM-DD inclusive")
    p.add_argument("--end", required=True, help="YYYY-MM-DD inclusive")
    p.add_argument("--universe", default="nasdaq100")
    p.add_argument("--top-n", type=int, default=3)
    p.add_argument("--template", default="balanced")
    p.add_argument("--model-name", default="deepseek-chat")
    p.add_argument("--model-provider", default="DeepSeek")
    p.add_argument("--windows", default="5,20")
    p.add_argument("--cost-bp", type=float, default=10.0,
                   help="Round-trip transaction cost in basis points per "
                        "non-HOLD decision (default: 10 = 0.10%%). Set 0 to "
                        "disable.")
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--max-days", type=int, default=None,
                   help="Cap on days (smoke testing).")
    return p.parse_args()


def main() -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    for name in ("urllib3", "httpx", "yfinance"):
        logging.getLogger(name).setLevel(logging.WARNING)

    args = _parse_args()
    windows = tuple(int(w.strip()) for w in args.windows.split(",") if w.strip())
    out_path = args.out or Path(f"outputs/ab_quant_ablation_{args.start}_{args.end}.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    from v2.backtesting.trading_calendar import trading_days_between
    from v2.data.factory import get_provider_factory

    factory = get_provider_factory()
    client = factory()
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
    if args.max_days:
        trading_days = trading_days[:args.max_days]

    print(f"Quant-ablation A/B: {len(trading_days)} trading days "
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
            )
        except KeyboardInterrupt:
            print("Interrupted — writing partial results")
            break
        except Exception as e:
            logger.exception("[%s] day failed: %s", day, e)
            day_rows = []
        all_rows.extend(day_rows)
        _write_csv(all_rows, out_path, windows)

    print(f"\nAll {len(trading_days)} days done in {time.monotonic() - t_start:.0f}s")
    print(f"Computing forward PnL for {len(all_rows)} decisions (cost={args.cost_bp:g} bp)...")
    _attach_forward_pnl(all_rows, windows=windows, cost_bp=args.cost_bp)
    _write_csv(all_rows, out_path, windows)
    print(f"Wrote {out_path} ({len(all_rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
