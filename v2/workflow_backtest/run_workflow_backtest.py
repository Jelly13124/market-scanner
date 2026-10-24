"""Workflow-backtest capstone — wire scanner/random arms through the agent
pipeline over a regime schedule, attribute forward returns, A/B them, and
sim portfolios. Everything the runner needs (scan fn, hedge-fund fn, provider
factory, outcome client) is INJECTED, so the offline smoke pays no network/LLM
cost; the CLI binds those seams to the live functions for the paid run.

Per (scan_date, arm) decisions are persisted to ``out_dir`` as JSON so a long
paid run is RESUMABLE — a cell whose file already exists is loaded back instead
of recomputed. No single cell can abort the run: each arm-decision call is
wrapped in try/except and its failure recorded, never raised.

Flow per scan_date (under ``asof_agent_context`` so all agent data reads are
clamped to that date):

  1. scanner arm: ``scanner_arm`` (top-N picks + scanner_context) →
     ``run_arm_decisions``.
  2. random  arm: ``random_arm`` (seeded sample) → ``run_arm_decisions`` with
     empty scanner_context.

After all dates: forward-return attribution per arm (UNCLAMPED ``fd`` so
outcomes aren't truncated to the as-of point), Welch A/B of direction-adjusted
21d SIGNAL returns of directional bets (long+short) per regime, equal-weight
fixed-hold portfolio sim per arm (post-cutoff dates), then ``report.write``.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict

from v2.workflow_backtest import report
from v2.workflow_backtest.arms import random_arm, scanner_arm
from v2.workflow_backtest.asof_agents import asof_agent_context
from v2.workflow_backtest.asof_dispatcher import AsOfDispatcher
from v2.workflow_backtest.attribution import ab_welch, attach_forward_returns
from v2.workflow_backtest.bundles import build_bundles
from v2.workflow_backtest.decisions import run_arm_decisions
from v2.workflow_backtest.portfolio import simulate
from v2.workflow_backtest.types import ArmResult, Decision

_ARMS = ("scanner", "random")
_FWD_WINDOWS = (21, 42, 63)
_BENCHMARK = "SPY"


# ---------------------------------------------------------------------------
# Resumable per-cell persistence
# ---------------------------------------------------------------------------


def _cell_path(out_dir, scan_date, arm):
    return os.path.join(out_dir, f"cell_{scan_date}_{arm}.json")


def _arm_result_to_dict(ar: ArmResult) -> dict:
    return {
        "arm": ar.arm,
        "scan_date": ar.scan_date,
        "tickers": list(ar.tickers),
        "error": ar.error,
        "decisions": {t: asdict(d) for t, d in ar.decisions.items()},
    }


def _arm_result_from_dict(d: dict) -> ArmResult:
    decisions = {
        t: Decision(
            ticker=dd.get("ticker", t),
            action=dd.get("action", "hold"),
            quantity=int(dd.get("quantity") or 0),
            confidence=dd.get("confidence"),
            reasoning=dd.get("reasoning"),
        )
        for t, dd in (d.get("decisions") or {}).items()
    }
    return ArmResult(
        arm=d["arm"],
        scan_date=d["scan_date"],
        tickers=list(d.get("tickers") or []),
        decisions=decisions,
        error=d.get("error"),
    )


def _load_cell(out_dir, scan_date, arm) -> ArmResult | None:
    path = _cell_path(out_dir, scan_date, arm)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return _arm_result_from_dict(json.load(fh))
    except Exception:
        return None


def _save_cell(out_dir, ar: ArmResult) -> None:
    path = _cell_path(out_dir, ar.scan_date, ar.arm)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(_arm_result_to_dict(ar), fh, indent=2)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Per-arm cell execution (never raises)
# ---------------------------------------------------------------------------


def _run_scanner_cell(*, scan_date, universe_tickers, top_n, provider_factory,
                      model_name, model_provider, run_scan_fn, run_hedge_fund_fn) -> ArmResult:
    try:
        tickers, ctx = scanner_arm(
            scan_date=scan_date, universe_tickers=universe_tickers, top_n=top_n,
            provider_factory=provider_factory, run_scan_fn=run_scan_fn,
        )
    except Exception as e:  # scan itself blew up — record, keep run alive
        return ArmResult(arm="scanner", scan_date=scan_date, tickers=[],
                         error=f"scan: {type(e).__name__}: {e}")
    return run_arm_decisions(
        arm="scanner", scan_date=scan_date, tickers=tickers, scanner_context=ctx,
        model_name=model_name, model_provider=model_provider, run_hedge_fund_fn=run_hedge_fund_fn,
    )


def _run_random_cell(*, scan_date, universe_tickers, top_n, seed,
                     model_name, model_provider, run_hedge_fund_fn) -> ArmResult:
    try:
        tickers = random_arm(scan_date=scan_date, universe_tickers=universe_tickers, n=top_n, seed=seed)
    except Exception as e:
        return ArmResult(arm="random", scan_date=scan_date, tickers=[],
                         error=f"sample: {type(e).__name__}: {e}")
    return run_arm_decisions(
        arm="random", scan_date=scan_date, tickers=tickers, scanner_context={},
        model_name=model_name, model_provider=model_provider, run_hedge_fund_fn=run_hedge_fund_fn,
    )


# ---------------------------------------------------------------------------
# Post-loop aggregation helpers
# ---------------------------------------------------------------------------


def _bundle_close_map(bundles) -> dict:
    """``{ticker: {date: close}}`` from bundle price bars (adjusted_close pref)."""
    out: dict[str, dict] = {}
    for ticker, bundle in (bundles or {}).items():
        series: dict[str, float] = {}
        for p in getattr(bundle, "prices", None) or []:
            d = getattr(p, "time", None)
            if not d:
                continue
            close = getattr(p, "adjusted_close", None)
            if close is None:
                close = getattr(p, "close", None)
            if close is not None:
                series[d[:10]] = float(close)
        if series:
            out[ticker] = series
    return out


def _all_price_dates(close_map) -> list[str]:
    dates: set[str] = set()
    for series in close_map.values():
        dates.update(series.keys())
    return sorted(dates)


def _fetch_benchmark(fd, *, start, end):
    try:
        return fd.get_prices(_BENCHMARK, start, end)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_workflow_backtest(
    *,
    universe_tickers,
    schedule,
    model_name,
    model_provider,
    top_n,
    seed,
    hold_days,
    out_dir,
    provider_factory,
    fd,
    run_scan_fn=None,
    run_hedge_fund_fn=None,
    bundles=None,
) -> dict:
    os.makedirs(out_dir, exist_ok=True)

    scan_dates = [row["scan_date"] for row in schedule]
    regime_by_date = {row["scan_date"]: row for row in schedule}

    # Build (or accept) the as-of bundles, then the dispatcher.
    if bundles is None:
        import datetime as _dt

        span_start = min(scan_dates) if scan_dates else None
        span_end = max(scan_dates) if scan_dates else None
        if span_start and span_end:
            # Lookback so agents (run_hedge_fund uses scan_date-250d) + scanner
            # detectors have price history BEFORE the earliest scan date; forward
            # buffer so the portfolio sim has bars to mark + exit positions AFTER
            # the latest scan date. 400/120 days mirror the scanner-eval prefetch.
            span_start = (_dt.date.fromisoformat(span_start[:10]) - _dt.timedelta(days=400)).isoformat()
            span_end = (_dt.date.fromisoformat(span_end[:10]) + _dt.timedelta(days=120)).isoformat()
        bundles = build_bundles(
            universe_tickers, provider_factory, span_start, span_end, enrich=False,
        )
    dispatcher = AsOfDispatcher(bundles)

    # --- per-date loop: scanner + random arms -----------------------------
    arms_ran: dict[str, list[str]] = {}
    results_by_date: dict[str, dict[str, ArmResult]] = {}

    for row in schedule:
        scan_date = row["scan_date"]
        per_arm: dict[str, ArmResult] = {}
        with asof_agent_context(dispatcher, scan_date):
            # scanner
            ar = _load_cell(out_dir, scan_date, "scanner")
            if ar is None:
                ar = _run_scanner_cell(
                    scan_date=scan_date, universe_tickers=universe_tickers, top_n=top_n,
                    provider_factory=provider_factory, model_name=model_name,
                    model_provider=model_provider, run_scan_fn=run_scan_fn,
                    run_hedge_fund_fn=run_hedge_fund_fn,
                )
                _save_cell(out_dir, ar)
            per_arm["scanner"] = ar

            # random
            ar = _load_cell(out_dir, scan_date, "random")
            if ar is None:
                ar = _run_random_cell(
                    scan_date=scan_date, universe_tickers=universe_tickers, top_n=top_n,
                    seed=seed, model_name=model_name, model_provider=model_provider,
                    run_hedge_fund_fn=run_hedge_fund_fn,
                )
                _save_cell(out_dir, ar)
            per_arm["random"] = ar

        results_by_date[scan_date] = per_arm
        arms_ran[scan_date] = [a for a in _ARMS if a in per_arm]

    # --- decision rows + forward-return attribution -----------------------
    close_map = _bundle_close_map(bundles)
    all_dates = _all_price_dates(close_map)
    bench_prices = _fetch_benchmark(
        fd, start=(all_dates[0] if all_dates else min(scan_dates, default="")),
        end=(all_dates[-1] if all_dates else max(scan_dates, default="")),
    )

    decision_rows: list[dict] = []
    # direction-adjusted SIGNAL returns keyed for A/B:
    #   {(regime_name, arm): [signal_ret_21d, ...]} over ALL bets (long + short)
    bets_by_regime_arm: dict[tuple, list] = {}
    regime_labels: dict[str, str] = {}

    for scan_date in scan_dates:
        meta = regime_by_date[scan_date]
        regime_name = meta.get("regime_name", "")
        regime_labels[regime_name] = meta.get("regime_label", "")
        per_arm = results_by_date.get(scan_date, {})
        for arm in _ARMS:
            ar = per_arm.get(arm)
            if ar is None:
                continue
            decision_list = list(ar.decisions.values())
            # forward returns for directional bets (buy+short) on this date/arm
            fwd_rows = attach_forward_returns(
                decision_list, fd, scan_date=scan_date, windows=_FWD_WINDOWS,
                benchmark_ticker=_BENCHMARK, benchmark_prices=bench_prices,
            )
            fwd_by_ticker = {r["ticker"]: r for r in fwd_rows}
            for d in decision_list:
                fr = fwd_by_ticker.get(d.ticker, {})
                decision_rows.append({
                    "scan_date": scan_date,
                    "arm": arm,
                    "regime_name": regime_name,
                    "regime_label": meta.get("regime_label", ""),
                    "is_post_cutoff": meta.get("is_post_cutoff", False),
                    "ticker": d.ticker,
                    "action": d.action,
                    "quantity": d.quantity,
                    "confidence": d.confidence,
                    "ret_21d": fr.get("ret_21d"),
                    "ret_42d": fr.get("ret_42d"),
                    "ret_63d": fr.get("ret_63d"),
                    "alpha_21d": fr.get("alpha_21d"),
                    "signal_ret_21d": fr.get("signal_ret_21d"),
                })
            for r in fwd_rows:
                # direction-adjusted signal return credits good long OR short calls
                bets_by_regime_arm.setdefault((regime_name, arm), []).append(r.get("signal_ret_21d"))

    # --- A/B Welch per regime (scanner bets vs random bets, direction-adjusted) ---
    ab_by_regime: dict[str, dict] = {}
    regimes = sorted({rn for (rn, _a) in bets_by_regime_arm} | set(regime_labels))
    for rn in regimes:
        scanner_bets = bets_by_regime_arm.get((rn, "scanner"), [])
        random_bets = bets_by_regime_arm.get((rn, "random"), [])
        ab = ab_welch(scanner_bets, random_bets)
        ab["regime_label"] = regime_labels.get(rn, "")
        ab_by_regime[rn] = ab

    # --- portfolio sim per arm (post-cutoff scan dates only) --------------
    trading_days = all_dates
    absolute_post_cutoff: dict[str, dict] = {}
    for arm in _ARMS:
        decisions_by_date: dict[str, list] = {}
        for scan_date in scan_dates:
            meta = regime_by_date[scan_date]
            if not meta.get("is_post_cutoff", False):
                continue
            ar = results_by_date.get(scan_date, {}).get(arm)
            if ar is None:
                continue
            bets = [d for d in ar.decisions.values() if d.action in ("buy", "short")]
            if bets:
                decisions_by_date.setdefault(scan_date, []).extend(bets)
        try:
            sim = simulate(
                decisions_by_date, close_map, trading_days=trading_days, hold_days=hold_days,
            )
        except Exception as e:
            absolute_post_cutoff[arm] = {"error": f"{type(e).__name__}: {e}"}
            continue
        ec = sim.get("equity_curve") or []
        final_value = ec[-1]["Portfolio Value"] if ec else None
        start_value = ec[0]["Portfolio Value"] if ec else None
        total_return = (
            (final_value / start_value - 1.0)
            if (final_value is not None and start_value not in (None, 0))
            else None
        )
        absolute_post_cutoff[arm] = {
            "final_value": final_value,
            "total_return": total_return,
            "metrics": sim.get("metrics") or {},
            "n_trades": len(sim.get("trades") or []),
        }

    # --- write report -----------------------------------------------------
    results = {
        "n_dates": len(scan_dates),
        "decision_rows": decision_rows,
        "ab_by_regime": ab_by_regime,
        "absolute_post_cutoff": absolute_post_cutoff,
    }
    paths = report.write(out_dir, results)

    return {
        "n_dates": len(scan_dates),
        "arms_ran": arms_ran,
        "ab_by_regime": ab_by_regime,
        "absolute_post_cutoff": absolute_post_cutoff,
        "report_path": paths["report_path"],
        "decisions_csv": paths["decisions_csv"],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _live_seams():
    """Bind scan/hedge-fund/provider/outcome seams to the LIVE (paid) functions.

    Imported lazily inside the CLI so the offline test never pulls these in.
    """
    from src.main import run_hedge_fund
    from v2.data.factory import get_provider_factory
    from v2.scanner.runner import run_scan

    provider_factory = get_provider_factory()
    return {
        "run_scan_fn": run_scan,
        "run_hedge_fund_fn": run_hedge_fund,
        "provider_factory": provider_factory,
        "fd": provider_factory(),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Agent workflow A/B backtest (scanner vs random).")
    parser.add_argument("--universe", default="nasdaq100")
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--every", type=int, default=5)
    parser.add_argument("--model", default="deepseek-v4-pro")
    parser.add_argument("--provider", default="DeepSeek")
    parser.add_argument("--hold-days", type=int, default=21)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out-dir", default="workflow_backtest")
    parser.add_argument("--smoke", action="store_true",
                        help="Offline smoke marker (paid path is exercised by the pytest smoke).")
    args = parser.parse_args(argv)

    if args.smoke:
        print("--smoke is validated by the offline pytest smoke "
              "(v2/workflow_backtest/test_runner_smoke.py); no paid run performed.")
        return 0

    # Live (paid) path needs API keys in os.environ. The SPY fetch below runs
    # BEFORE _live_seams() (which transitively loads .env via src.main), so load
    # it here explicitly — otherwise the provider 401s and the schedule is empty.
    from dotenv import load_dotenv
    load_dotenv()

    # Live (paid) path: resolve the real universe + a SPY-based regime schedule,
    # then bind the live seams. Kept lazy so an offline `--help` stays cheap.
    from v2.scanner.universes import load_universe
    from v2.data.factory import get_provider_factory
    from v2.workflow_backtest.regime_windows import build_schedule
    import datetime as _dt

    universe_tickers = load_universe(args.universe)
    pf = get_provider_factory()
    fd = pf()
    run_date = _dt.date.today().isoformat()
    spy = fd.get_prices(_BENCHMARK, "2018-01-01", run_date)
    # The full trading calendar = SPY's bar dates (a liquid daily proxy).
    trading_days = sorted({p.time[:10] for p in (spy or [])})
    schedule = build_schedule(trading_days, spy, run_date=run_date, every=args.every)

    seams = _live_seams()
    summary = run_workflow_backtest(
        universe_tickers=universe_tickers, schedule=schedule, model_name=args.model,
        model_provider=args.provider, top_n=args.top_n, seed=args.seed,
        hold_days=args.hold_days, out_dir=args.out_dir, **seams,
    )
    print(json.dumps({k: summary[k] for k in ("n_dates", "report_path", "decisions_csv")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
