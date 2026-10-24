"""Standalone Phase-3 confirmation run for the scanner eval.

Phases 1+2 (detector scorecard + signal IC) are already on disk in
scanner_eval/{detectors,signals}.csv. This runs ONLY Phase 3 — the bounded
full-replay that measures the real Top-N composite's 5d alpha per regime and the
quant overlay ON-vs-OFF ablation — using the SAME 80-ticker subset (the earlier
run had a bug that replayed the full 516). Days are EVEN-SAMPLED across each
regime (spread_days) so the alpha isn't estimated from a clump of adjacent,
near-identical Top-Ns.

Writes scanner_eval/phase3_summary.json (consumed by rerender_eval_report.py).

Usage:
    PYTHONPATH=. python scripts/run_phase3_eval.py [--max-tickers 80] [--spread-days 4] [--top-n 20]
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from dotenv import load_dotenv

from v2.data.factory import get_provider_factory
from v2.scanner.eval.phase3_backtest import run_phase3, summarize_phase3
from v2.scanner.eval.run_eval import _map_phase3
from v2.scanner.universes import load_universe
from scripts.rerender_eval_report import REGIMES

REPO = Path(__file__).resolve().parents[1]


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-tickers", type=int, default=80)
    ap.add_argument("--spread-days", type=int, default=4)
    ap.add_argument("--top-n", type=int, default=20)
    args = ap.parse_args()

    tickers = load_universe("nasdaq100_sp500")[: args.max_tickers]
    out_dir = REPO / "scanner_eval"
    logging.info("phase3 standalone: %d tickers, spread_days=%d, top_n=%d",
                 len(tickers), args.spread_days, args.top_n)

    rr = run_phase3(
        REGIMES,
        universe_kind="nasdaq100_sp500",
        universe_tickers=tickers,
        top_n=args.top_n,
        spread_days=args.spread_days,
        out_dir=out_dir,
        provider_factory=get_provider_factory(),
    )
    summary = summarize_phase3(rr)
    mapped = _map_phase3(summary)

    out_json = out_dir / "phase3_summary.json"
    out_json.write_text(json.dumps(mapped, indent=2), encoding="utf-8")
    logging.info("phase3 summary written to %s:\n%s", out_json, json.dumps(mapped, indent=2))


if __name__ == "__main__":
    main()
