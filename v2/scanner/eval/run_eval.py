"""Integration capstone for the scanner-evaluation harness.

``run_eval`` wires together everything the other eval modules built — regime
classification, the detector scorecard, the signal IC study, Phase-2 historical
enrichment, and the bounded Phase-3 full replay — into ONE overnight-unattended
run that produces the morning report at the repo root.

THE FAIL-SOFT CONTRACT (load-bearing)
-------------------------------------
The run is three phases, each wrapped in its own try/except, and the report is
REWRITTEN after every phase. So a partial run still leaves a readable report:

  * **Phase 1 (guaranteed)** — prefetch each ticker's PRICE history once, score
    every detector + signal on price-only bundles, write the CSVs, write the
    report. This is the floor: even if Phases 2–3 explode, the user wakes to a
    price-only scorecard.
  * **Phase 2 (best-effort, time-boxed)** — enrich each bundle with historical
    event / fundamental data (earnings, analyst, insider, news, financials),
    RE-score everything on the now-richer bundles, rewrite CSVs + report. Bounded
    by ``phase2_budget_min``; a per-ticker or whole-phase failure can't abort.
  * **Phase 3 (bounded)** — replay the REAL scanner Top-N per regime with the
    quant overlay ON vs OFF, summarise, rewrite the report with that block.

A phase failing logs the exception and moves on; it never prevents the report
that an earlier phase already wrote, nor aborts a later phase that can still run.

The cross-module collaborators are imported at module scope so tests can
monkeypatch them on THIS module (``run_eval`` reads them as module globals).
``run_eval`` is fully parameter-injectable and takes ``generated_at`` as an
argument (it does NOT call ``datetime.now()`` itself) so tests stay deterministic
and offline — ``main`` supplies the real timestamp.
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from v2.data.factory import get_provider_factory
from v2.scanner.detectors import ALL_DETECTORS
from v2.scanner.eval.cached_asof_client import TickerBundle
from v2.scanner.eval.detector_scorecard import score_all_detectors, write_detectors_csv
from v2.scanner.eval.historical_events import enrich_bundle
from v2.scanner.eval.phase3_backtest import run_phase3, summarize_phase3
from v2.scanner.eval.regimes import classify_regimes
from v2.scanner.eval.report import write_report
from v2.scanner.eval.signal_ic import score_all_signals, write_signals_csv
from v2.scanner.universes import load_universe
from v2.signals import ALL_SIGNALS

logger = logging.getLogger(__name__)

DEFAULT_OUT_DIR = "scanner_eval"
REPORT_NAME = "findings_scanner_eval.md"

#: Wide SPY span used to classify regimes before the per-ticker span is known.
#: The end is resolved from ``generated_at`` (or this fallback) so ``run_eval``
#: never calls ``datetime.now()`` itself.
_SPY_SPAN_START = "2021-06-01"
_SPY_SPAN_END_FALLBACK = "2025-08-15"

#: Calendar-day padding around the regime span for the price prefetch. Detector
#: lookbacks reach ~252 bars (≈ a year), so we pull ~400 days before the first
#: regime; forward returns reach 20 bars, so ~45 days after the last.
_LOOKBACK_DAYS = 400
_FORWARD_DAYS = 45


# ---------------------------------------------------------------------------
# Span helpers
# ---------------------------------------------------------------------------


def _shift_iso(iso: str, days: int) -> str:
    """``YYYY-MM-DD`` shifted by ``days`` (may be negative), reformatted."""
    from datetime import date, timedelta

    d = date.fromisoformat(iso[:10]) + timedelta(days=days)
    return d.isoformat()


def _full_span(regimes) -> tuple[str, str]:
    """Prefetch span: earliest regime.start − ~400d to latest regime.end + ~45d.

    Returns ``(start_iso, end_iso)``. The padding covers detector lookbacks
    (≈252 bars before) and forward-return horizons (20 bars after).
    """
    starts = [_attr(r, "start") for r in regimes if _attr(r, "start")]
    ends = [_attr(r, "end") for r in regimes if _attr(r, "end")]
    start = _shift_iso(min(starts), -_LOOKBACK_DAYS)
    end = _shift_iso(max(ends), _FORWARD_DAYS)
    return start, end


def _attr(obj, name, default=None):
    """``getattr`` for objects, ``.get`` for dicts — RegimeWindow OR dict."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


# ---------------------------------------------------------------------------
# Price prefetch (Phase 1 input)
# ---------------------------------------------------------------------------


def prefetch_price_bundles(tickers, provider_factory, start, end) -> dict:
    """Fetch each ticker's price history ONCE into a ``TickerBundle``.

    One client for the whole prefetch. Best-effort per ticker: a fetch failure
    logs and yields an empty bundle (which the scorers skip) rather than aborting
    the run. Progress is logged every ~25 tickers. The client is closed at the
    end. Returns ``{ticker: TickerBundle}``.
    """
    client = provider_factory()
    bundles: dict[str, TickerBundle] = {}
    total = len(tickers)
    try:
        for i, ticker in enumerate(tickers, 1):
            try:
                prices = client.get_prices(ticker, start, end)
            except Exception:
                logger.exception("prefetch get_prices failed for %s — empty bundle", ticker)
                prices = []
            bundles[ticker] = TickerBundle(ticker=ticker, prices=prices or [])
            if i % 25 == 0 or i == total:
                logger.info("prefetch %d/%d price bundles", i, total)
    finally:
        _safe_close(client)
    return bundles


def fetch_spy(provider_factory, start, end) -> list:
    """SPY price history over ``[start, end]``, best-effort → ``[]`` on failure."""
    client = provider_factory()
    try:
        return client.get_prices("SPY", start, end) or []
    except Exception:
        logger.exception("fetch_spy failed — no regime stats will be available")
        return []
    finally:
        _safe_close(client)


def _safe_close(client) -> None:
    close = getattr(client, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            logger.debug("client.close() failed", exc_info=True)


def _detectors():
    return [c() for c in ALL_DETECTORS]


def _signals():
    return [c() for c in ALL_SIGNALS]


# ---------------------------------------------------------------------------
# Phase-3 key mapping
# ---------------------------------------------------------------------------


def _map_phase3(summary: dict) -> dict:
    """Map ``summarize_phase3`` keys onto the keys ``report._render_phase3`` reads.

    ``summarize_phase3`` emits per regime ``mean_alpha_5d`` / ``quant_on_alpha``
    / ``quant_off_alpha`` / ``quant_delta`` (+ dir-alpha + counts). The report's
    phase-3 block reads ``mean_alpha_5d`` / ``quant_on`` / ``quant_off`` (and
    recomputes the ON−OFF delta itself). So we rename ``quant_on_alpha`` →
    ``quant_on`` and ``quant_off_alpha`` → ``quant_off`` and carry the rest.
    """
    out: dict = {}
    for name, d in summary.items():
        out[name] = {
            "mean_alpha_5d": d.get("mean_alpha_5d"),
            "quant_on": d.get("quant_on_alpha"),
            "quant_off": d.get("quant_off_alpha"),
            "quant_delta": d.get("quant_delta"),
        }
    return out


# ---------------------------------------------------------------------------
# run_eval
# ---------------------------------------------------------------------------


def run_eval(
    *,
    universe: str = "nasdaq100_sp500",
    max_tickers: int | None = None,
    phase2_budget_min: float = 90,
    phase3_max_days: int = 8,
    do_phase3: bool = True,
    out_dir: str = DEFAULT_OUT_DIR,
    provider_factory=None,
    generated_at: str | None = None,
) -> Path:
    """Run the full scanner evaluation in three fail-soft phases; return the
    report path (at the repo root, NOT under ``out_dir`` — the user reads it
    there each morning).

    Every phase is isolated: a phase raising logs the exception and the run
    continues, so a failure in Phase 2 or 3 never erases the Phase-1 report nor
    blocks a later phase. ``generated_at`` is taken as an argument (never
    ``datetime.now()`` here) to keep tests deterministic.
    """
    # --- 1. Setup -----------------------------------------------------------
    provider_factory = provider_factory or get_provider_factory()
    tickers = load_universe(universe)
    if max_tickers is not None:
        tickers = tickers[:max_tickers]
    logger.info("eval universe=%s tickers=%d (max_tickers=%s)", universe, len(tickers), max_tickers)

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    report_path = _repo_root() / REPORT_NAME
    if generated_at is None:
        generated_at = "(pending)"

    # --- 2. SPY + regimes ---------------------------------------------------
    spy_end = generated_at[:10] if generated_at and generated_at[0].isdigit() else _SPY_SPAN_END_FALLBACK
    spy_prices = fetch_spy(provider_factory, _SPY_SPAN_START, spy_end)
    regimes = classify_regimes(spy_prices)
    span = _full_span(regimes)
    logger.info("regimes=%d prefetch span=%s..%s", len(regimes), span[0], span[1])

    # --- 3. Prefetch price bundles -----------------------------------------
    bundles = prefetch_price_bundles(tickers, provider_factory, span[0], span[1])

    detectors_csv = out_path / "detectors.csv"
    signals_csv = out_path / "signals.csv"

    detector_rows: list[dict] = []
    signal_rows: list[dict] = []

    def _rewrite_report(phase3=None) -> None:
        write_report(
            report_path,
            detector_rows=detector_rows,
            signal_rows=signal_rows,
            regimes=regimes,
            phase3=phase3,
            universe=universe,
            generated_at=generated_at,
        )

    # --- 4. PHASE 1 (guaranteed): price-only scorecard ---------------------
    try:
        detector_rows = score_all_detectors(_detectors(), regimes, bundles, spy_prices)
        signal_rows = score_all_signals(_signals(), regimes, bundles)
        write_detectors_csv(detector_rows, detectors_csv)
        write_signals_csv(signal_rows, signals_csv)
        _rewrite_report(phase3=None)
        logger.info("phase 1 complete: %d detector rows, %d signal rows", len(detector_rows), len(signal_rows))
    except Exception:
        logger.exception("phase 1 failed — attempting to write whatever rows exist")
        try:
            _rewrite_report(phase3=None)
        except Exception:
            logger.exception("phase 1 report write also failed")

    # --- 5. PHASE 2 (best-effort, time-boxed): enrich + re-score -----------
    try:
        deadline = time.monotonic() + float(phase2_budget_min) * 60.0
        client = provider_factory()
        try:
            enriched = 0
            for bundle in bundles.values():
                if time.monotonic() >= deadline:
                    logger.warning("phase 2 budget exhausted after %d tickers — stopping enrichment", enriched)
                    break
                try:
                    enrich_bundle(
                        bundle,
                        start_date=span[0],
                        end_date=span[1],
                        insider_client=client,
                        news_client=client,
                        deadline=deadline,
                    )
                    enriched += 1
                except Exception:
                    logger.exception("enrich_bundle failed for %s — leaving price-only", _attr(bundle, "ticker"))
        finally:
            _safe_close(client)

        detector_rows = score_all_detectors(_detectors(), regimes, bundles, spy_prices)
        signal_rows = score_all_signals(_signals(), regimes, bundles)
        write_detectors_csv(detector_rows, detectors_csv)
        write_signals_csv(signal_rows, signals_csv)
        _rewrite_report(phase3=None)
        logger.info("phase 2 complete: enriched %d bundles, re-scored", enriched)
    except Exception:
        logger.exception("phase 2 failed — keeping Phase-1 report")

    # --- 6. PHASE 3 (bounded): full-replay confirmation --------------------
    phase3_mapped = None
    if do_phase3:
        try:
            rr = run_phase3(
                regimes,
                universe_kind=universe,
                top_n=20,
                max_days=phase3_max_days,
                out_dir=out_path,
                provider_factory=provider_factory,
            )
            summary = summarize_phase3(rr)
            phase3_mapped = _map_phase3(summary)
            _rewrite_report(phase3=phase3_mapped)
            logger.info("phase 3 complete: %d regimes summarised", len(phase3_mapped))
        except Exception:
            logger.exception("phase 3 failed — keeping the pre-phase-3 report")

    return report_path


def _repo_root() -> Path:
    """Repo root = three parents up from this file (``v2/scanner/eval/``)."""
    return Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv=None):
    from datetime import datetime

    parser = argparse.ArgumentParser(description="Run the scanner detector/signal usefulness evaluation (3 fail-soft phases).")
    parser.add_argument("--universe", default="nasdaq100_sp500", help="Universe kind to evaluate.")
    parser.add_argument("--max-tickers", type=int, default=None, help="Cap the universe to the first N tickers.")
    parser.add_argument("--phase2-budget-min", type=float, default=90, help="Time box (minutes) for Phase-2 enrichment.")
    parser.add_argument("--phase3-max-days", type=int, default=8, help="Bounded replay length (days) per Phase-3 regime arm.")
    parser.add_argument("--no-phase3", action="store_true", help="Skip Phase 3 entirely.")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help="Directory for CSVs + Phase-3 artifacts.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    generated_at = datetime.now().isoformat(timespec="minutes")

    report_path = run_eval(
        universe=args.universe,
        max_tickers=args.max_tickers,
        phase2_budget_min=args.phase2_budget_min,
        phase3_max_days=args.phase3_max_days,
        do_phase3=not args.no_phase3,
        out_dir=args.out_dir,
        generated_at=generated_at,
    )
    print(f"Eval report written to: {report_path}")
    return report_path


if __name__ == "__main__":
    main()
