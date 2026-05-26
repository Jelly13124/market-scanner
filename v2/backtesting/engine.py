"""v2 backtesting engine.

Replays ``v2.scanner.runner.run_scan`` over a historical date range and
joins each scored entry with its forward 1d/5d/20d/63d returns + the
benchmark-relative alpha for the same windows. Output is a single CSV
plus a console summary.

The whole point of this is to convert "the watchlist looks good" into
"the watchlist generated +X bp/day vs SPY at top-rank decile" — i.e. a
measurable claim. CSV opens in any pandas / Jupyter session for ad-hoc
analysis (per-detector contribution, multi-detector confluence, decile
spread, etc.).

V1 design notes:
  * **Sequential days** — keeps the loop deterministic and lets the
    existing per-day ThreadPool (inside ``run_scan``) handle ticker-level
    parallelism. A 250-day backtest on SP500 takes hours, not minutes;
    callers are expected to start with ``--max-days N`` smoke runs.
  * **Benchmark series fetched ONCE** at the start, reused for every
    ticker × date forward-return computation. Without that we'd pull SPY
    250×500 = 125k times.
  * **target_price_change excluded** — needs DB snapshots we can't
    backfill historically. ``earnings_upcoming`` also functionally
    disabled (we pass ``upcoming_earnings=None``; the detector returns
    None per ticker → no triggers but no crashes). Documented in CLI.
  * **No quant signals** — adding momentum/value/quality would slow each
    scan further and v1 just wants to measure pure detector signal.
"""

from __future__ import annotations

import csv
import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from v2.backtesting.forward_returns import compute_forward_returns, direction_adjust
from v2.backtesting.trading_calendar import trading_days_between
from v2.data.factory import get_provider_factory
from v2.scanner.detectors import ALL_DETECTORS
from v2.scanner.models import ScannerWeights, ScoredEntry
from v2.scanner.runner import run_scan
from v2.scanner.universes import load_universe

logger = logging.getLogger(__name__)


# Detectors that cannot replay historically. ``target_price_change``
# needs daily DB snapshots of analyst targets that we don't have for
# past dates (M9.d only persists snapshots going FORWARD from when it
# was deployed).
SKIP_FOR_BACKTEST: frozenset[str] = frozenset({"target_price_change"})


# Forward-return windows in trading days. 1/5/20/63 ≈ same-day / week /
# month / quarter. Pinned so CSV column names are stable across runs.
DEFAULT_WINDOWS: tuple[int, ...] = (1, 5, 20, 63)


CSV_COLUMNS: tuple[str, ...] = (
    "scan_date",
    "ticker",
    "rank",
    "composite_score",
    "direction",
    "event_severity",
    "n_detectors_triggered",
    "triggered_detectors",
    "triggered_components_json",
    "close_at_scan",
    "ret_1d", "ret_5d", "ret_20d", "ret_63d",
    "bench_ret_1d", "bench_ret_5d", "bench_ret_20d", "bench_ret_63d",
    "alpha_1d", "alpha_5d", "alpha_20d", "alpha_63d",
    "dir_ret_5d", "dir_alpha_5d",
)


def _build_detector_list():
    """Active detectors for backtest = ALL_DETECTORS minus skip-list."""
    out = []
    for cls in ALL_DETECTORS:
        inst = cls()
        if inst.name in SKIP_FOR_BACKTEST:
            continue
        out.append(inst)
    return out


def _entry_to_row(
    *, scan_date: str, entry: ScoredEntry,
    fwd: dict[str, float | None],
) -> dict[str, Any]:
    """Flatten one ScoredEntry + its forward returns into a CSV row dict."""
    triggered = [
        t for t in entry.triggers
        if isinstance(t, dict) and t.get("triggered")
    ]
    triggered_names = sorted({t["detector"] for t in triggered if t.get("detector")})

    # Per-detector components dict — keeps the analysis-time dives (BREAK by
    # horizon, INSDR strict-buy filter, etc.) computable from the CSV alone
    # without re-running the scan. Compact JSON (no whitespace) keeps CSV
    # size manageable; ~200-500 chars per row on a typical Top-N entry.
    triggered_components = {
        t["detector"]: t.get("components", {})
        for t in triggered if t.get("detector")
    }

    dir_ret_5d = direction_adjust(fwd.get("ret_5d"), entry.direction)
    dir_alpha_5d = direction_adjust(fwd.get("alpha_5d"), entry.direction)

    return {
        "scan_date": scan_date,
        "ticker": entry.ticker,
        "rank": entry.rank,
        "composite_score": round(entry.composite_score, 4),
        "direction": entry.direction,
        "event_severity": round(entry.event_severity, 4),
        "n_detectors_triggered": len(triggered_names),
        "triggered_detectors": "|".join(triggered_names),
        "triggered_components_json": json.dumps(triggered_components, separators=(",", ":")),
        "close_at_scan": fwd.get("close_at_scan"),
        "ret_1d": fwd.get("ret_1d"),
        "ret_5d": fwd.get("ret_5d"),
        "ret_20d": fwd.get("ret_20d"),
        "ret_63d": fwd.get("ret_63d"),
        "bench_ret_1d": fwd.get("bench_ret_1d"),
        "bench_ret_5d": fwd.get("bench_ret_5d"),
        "bench_ret_20d": fwd.get("bench_ret_20d"),
        "bench_ret_63d": fwd.get("bench_ret_63d"),
        "alpha_1d": fwd.get("alpha_1d"),
        "alpha_5d": fwd.get("alpha_5d"),
        "alpha_20d": fwd.get("alpha_20d"),
        "alpha_63d": fwd.get("alpha_63d"),
        "dir_ret_5d": dir_ret_5d,
        "dir_alpha_5d": dir_alpha_5d,
    }


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value*100:+.3f}%"


def _print_summary(rows: list[dict[str, Any]], scans_run: int) -> None:
    """One-page console digest of the CSV: counts + mean alpha + per-detector breakout."""
    print()
    print("=" * 60)
    print(f"Backtest complete: {scans_run} scans, {len(rows)} entries")
    print("=" * 60)
    if not rows:
        print("(no entries produced)")
        return

    def _mean(values: list[float | None]) -> float | None:
        clean = [v for v in values if v is not None]
        return sum(clean) / len(clean) if clean else None

    overall_alpha_5d = _mean([r["alpha_5d"] for r in rows])
    overall_dir_alpha_5d = _mean([r["dir_alpha_5d"] for r in rows])
    print(f"Mean alpha_5d (raw):              {_fmt_pct(overall_alpha_5d)}")
    print(f"Mean alpha_5d (dir-adjusted):     {_fmt_pct(overall_dir_alpha_5d)}")

    # Per-detector breakout: for each detector, mean dir_alpha_5d of entries
    # where that detector contributed (even alongside others). NOT pure
    # attribution — that's an external pandas analysis on the CSV.
    per_det: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r["dir_alpha_5d"] is None or not r["triggered_detectors"]:
            continue
        for d in r["triggered_detectors"].split("|"):
            per_det[d].append(r["dir_alpha_5d"])

    print()
    print("Per-detector mean dir_alpha_5d (entries where it co-fired):")
    print(f"  {'detector':<25s} {'n':>5s}  {'mean':>10s}")
    for det in sorted(per_det.keys()):
        vals = per_det[det]
        avg = sum(vals) / len(vals)
        print(f"  {det:<25s} {len(vals):>5d}  {_fmt_pct(avg):>10s}")

    print()
    print(
        "NOTE: universe is the CURRENT snapshot — backtest excludes "
        "delisted/merged companies (survivorship bias)."
    )


def run_backtest(
    *,
    universe_kind: str,
    universe_tickers: list[str] | None,
    weights_payload: dict | None,
    start_date: str,
    end_date: str,
    top_n: int,
    output_path: Path,
    benchmark_ticker: str = "SPY",
    max_days: int | None = None,
    provider_factory=None,
    use_quant_signals: bool = True,
) -> int:
    """Execute a backtest and write CSV. Returns the number of rows written.

    Sequential per-day loop. Inside each day ``run_scan`` parallelizes
    across tickers via its own ThreadPool. Per CLAUDE.md per-worker
    DataClient rule we don't share a client across days — each call to
    ``run_scan`` builds its own pool.

    Forward-return computation uses a SEPARATE single client (not from
    the scan pool) for two reasons: (a) the scan pool is closed after
    each ``run_scan`` returns, (b) forward fetches happen AFTER the
    per-day scan, sequentially within the same Python thread.
    """
    if provider_factory is None:
        provider_factory = get_provider_factory()

    tickers = load_universe(universe_kind, custom=universe_tickers)
    if not tickers:
        raise ValueError(f"Empty universe: kind={universe_kind!r}")

    det_list = _build_detector_list()
    weights = ScannerWeights(**(weights_payload or {}))

    # Quant signals — production scanner has these wired in
    # ScannerService (composite_score = event_weight * event_score +
    # quant_weight * quant_score). Backtest historically defaulted to
    # detector-only (None); flag now lets us toggle for ablation.
    quant_instances = None
    if use_quant_signals:
        from v2.signals import ALL_SIGNALS
        quant_instances = [cls() for cls in ALL_SIGNALS]
        logger.info("Backtest using %d quant signals", len(quant_instances))
    else:
        logger.info("Backtest WITHOUT quant signals (ablation mode)")

    # One client to enumerate trading days + fetch benchmark + forward
    # prices. Lives for the entire backtest.
    helper_client = provider_factory()
    try:
        days = trading_days_between(
            helper_client, start_date=start_date, end_date=end_date,
        )
        if max_days is not None:
            days = days[:max_days]
        if not days:
            raise ValueError(
                f"No trading days between {start_date} and {end_date}"
            )

        # Pre-fetch benchmark series for the full forward span ONCE. We
        # need bars from start_date through (last_scan_date + max_window).
        max_win = max(DEFAULT_WINDOWS)
        last_day = datetime.strptime(days[-1], "%Y-%m-%d").date()
        bench_end = (last_day + timedelta(days=int(max_win * 1.6) + 7)).isoformat()
        logger.info("Fetching benchmark %s from %s to %s",
                    benchmark_ticker, start_date, bench_end)
        benchmark_prices = helper_client.get_prices(
            benchmark_ticker, start_date, bench_end,
        )
        if not benchmark_prices:
            logger.warning(
                "Benchmark %s returned no bars — alpha columns will be None",
                benchmark_ticker,
            )
            benchmark_prices = []

        rows: list[dict[str, Any]] = []
        t_start = time.monotonic()
        for i, scan_date in enumerate(days, start=1):
            print(
                f"[{i}/{len(days)}] {scan_date} — scanning {len(tickers)} tickers...",
                flush=True,
            )
            day_start = time.monotonic()
            try:
                scored = run_scan(
                    tickers=tickers,
                    end_date=scan_date,
                    top_n=top_n,
                    weights=weights,
                    detectors=det_list,
                    quant_signals=quant_instances,
                    max_workers=16,
                    provider_factory=provider_factory,
                    benchmark_ticker=benchmark_ticker,
                )
            except Exception as e:
                logger.error("run_scan failed for %s: %s", scan_date, e)
                continue

            # Forward returns per entry, using the shared benchmark series.
            for entry in scored:
                fwd = compute_forward_returns(
                    helper_client,
                    ticker=entry.ticker,
                    scan_date=scan_date,
                    windows=DEFAULT_WINDOWS,
                    benchmark_ticker=benchmark_ticker,
                    benchmark_prices=benchmark_prices,
                )
                rows.append(_entry_to_row(scan_date=scan_date, entry=entry, fwd=fwd))

            day_elapsed = time.monotonic() - day_start
            print(
                f"   → {len(scored)} entries, {day_elapsed:.1f}s "
                f"(total {time.monotonic() - t_start:.0f}s)",
                flush=True,
            )

        # Write CSV
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(CSV_COLUMNS))
            writer.writeheader()
            for r in rows:
                writer.writerow(r)
        print()
        print(f"Wrote {len(rows)} rows to {output_path}")

        _print_summary(rows, scans_run=len(days))
        return len(rows)

    finally:
        try:
            helper_client.close()
        except Exception:
            pass
