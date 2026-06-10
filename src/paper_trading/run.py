"""CLI + scheduler entrypoints for the paper-trading forward test (Task 8).

This ties the harness into a runnable system. The DB is the source of truth: the
in-memory broker does not persist across runs, so each ``--once`` run RECONSTRUCTS
a per-sleeve :class:`FakeBroker` from the DB (cash + open lots) and marks it at
REAL market prices. No broker key is needed for the default path; the optional
``AlpacaBroker`` adapter is a separate future-execution seam.

Subcommands (combinable):
    --once     Run THIS week's rebalance for all sleeves.
    --marks    Mark every sleeve to market for today (daily MTM).
    --report   Write the Markdown + HTML report to ``--out-dir``.

Overrides:
    --scan-date YYYY-MM-DD   As-of date for the scan/marks (default: today).
    --week-key  YYYY-Www     ISO-week idempotency key (default: derived).
    --out-dir   PATH         Report output dir (default: paper_trading_report).
    --universe  KIND         Scanner universe (default: nasdaq100).
    --top-n     N            Ranked picks per scan (default: 5).
    --model / --provider     Agent LLM (default: deepseek-v4-pro / DeepSeek).

The real provider/scanner/agent seams are built lazily (``_live_seams``) so a
``--report``-only run needs none of them installed. ``load_dotenv()`` runs at
import so provider/LLM keys are present (a prior CLI 401'd without it).
"""

from __future__ import annotations

import argparse
import logging
from datetime import date

from dotenv import load_dotenv

load_dotenv()  # populate provider/LLM keys before any seam runs (lesson: 401 without it)

from app.backend.database import SessionLocal  # noqa: E402

from .marks import mark_all  # noqa: E402
from .report import write_report  # noqa: E402
from .sleeves import active_sleeves, compute_targets  # noqa: E402
from .state import reconstruct_broker  # noqa: E402

logger = logging.getLogger(__name__)

# Defaults mirror the workflow-backtest CLI so the live A/B uses the same knobs.
DEFAULT_UNIVERSE = "nasdaq100"
DEFAULT_TOP_N = 5
DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_PROVIDER = "DeepSeek"
DEFAULT_HOLD_DAYS = 30
DEFAULT_OUT_DIR = "paper_trading_report"
DEFAULT_STARTING_CASH = 100_000.0


def week_key_for(scan_date: str) -> str:
    """Derive the ISO ``YYYY-Www`` week key for ``scan_date`` (e.g. ``2026-W24``)."""
    iso = date.fromisoformat(scan_date).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


# ---------------------------------------------------------------------------
# Live seams — lazily imported so --report alone pulls in no providers/LLM.
# ---------------------------------------------------------------------------


def _live_seams(*, universe: str, model: str, provider: str):
    """Bind the scan / agent / factor / price seams to the LIVE (paid) functions.

    Returns ``(run_scan_fn, agent_fn, factor_fn, price_fn, universe_tickers)``.
    Imports are deferred to here so importing this module (and running
    ``--report``) never drags in the scanner/agent/data/self-evolve stack.
    """
    from v2.data.factory import get_provider_factory
    from v2.pipeline.orchestrator import run_agents_only
    from v2.scanner.runner import run_scan
    from v2.scanner.universes.loader import load_universe
    from v2.self_evolve.graduate import build_factor_fn

    provider_factory = get_provider_factory()
    universe_tickers = load_universe(universe)

    def run_scan_fn(scan_date: str, top_n: int) -> list[str]:
        """Adapt ``run_scan`` → a ranked list of ticker strings (mirrors scanner_arm)."""
        entries = run_scan(
            tickers=universe_tickers,
            end_date=scan_date,
            top_n=top_n,
            provider_factory=provider_factory,
        )
        return [e.ticker for e in entries]

    def agent_fn(tickers: list[str], scan_date: str) -> dict[str, dict]:
        """Adapt ``run_agents_only`` → ``{ticker: {action, ...}}`` (mirrors run_arm_decisions)."""
        out = run_agents_only(
            tickers=tickers,
            scan_date=scan_date,
            model_name=model,
            model_provider=provider,
        )
        return out.get("decisions") or {}

    # factor_evolved sleeve: the best self-evolved factor config's book. Built
    # over the SAME universe/provider as the scanner so the A/B is apples-to-apples.
    factor_fn = build_factor_fn(provider_factory, universe_tickers)

    def price_fn(ticker: str) -> float | None:
        """Latest close via the data layer (best-effort, None on failure)."""
        return _latest_close(ticker, provider_factory)

    return run_scan_fn, agent_fn, factor_fn, price_fn, universe_tickers


def _latest_close(ticker: str, provider_factory, *, asof: str | None = None) -> float | None:
    """Return ``ticker``'s latest close on/at ``asof`` (today if None). None on any failure.

    Mirrors ``src/research/shared_data.py``: a fresh client from the factory,
    a ~400-day lookback window, take the last bar's ``close``.
    """
    from datetime import datetime, timedelta

    end = asof or date.today().isoformat()
    try:
        start = (datetime.strptime(end, "%Y-%m-%d").date() - timedelta(days=400)).isoformat()
        client = provider_factory()
        try:
            prices = client.get_prices(ticker, start, end)
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        if not prices:
            return None
        return float(prices[-1].close)
    except Exception as exc:  # noqa: BLE001 — best-effort price, never raise
        logger.warning("price_fn: %s @ %s failed: %s", ticker, end, exc)
        return None


# ---------------------------------------------------------------------------
# Per-action drivers (used by both the CLI and the scheduler jobs).
# ---------------------------------------------------------------------------


def run_once(
    *,
    session,
    run_scan_fn,
    agent_fn,
    price_fn,
    factor_fn=None,
    scan_date: str,
    week_key: str,
    top_n: int = DEFAULT_TOP_N,
    hold_days: int | None = DEFAULT_HOLD_DAYS,
    starting_cash: float = DEFAULT_STARTING_CASH,
) -> dict[str, dict]:
    """Run this week's rebalance for all sleeves; never crash on one sleeve.

    For each sleeve: compute the union of (held + target) tickers, fetch a live
    ``prices`` mark for each, reconstruct the sleeve's broker from the DB at
    those marks, then drive :func:`run_week`. One sleeve raising is logged and
    skipped so the others still run.

    Per-sleeve institutional-flow gating: before each sleeve computes its targets
    (the agent runs inside ``compute_targets``), the research agent's flow context
    is toggled ON only for ``scanner_agent_flow`` and OFF for every other sleeve.
    So ``scanner_agent`` (flow OFF) vs ``scanner_agent_flow`` (flow ON) is a clean
    with/without-flow A/B — the agent runs TWICE per week, once each way. The
    default (flow ON for normal Analyze) is restored in a ``finally`` so a paper
    run never leaks a disabled flag into the rest of the process.

    Returns ``{sleeve_name: run_week summary | {"error": str}}``.
    """
    from .engine import run_week

    # Lazily bind the flow gate; if quant_context can't be imported, fall back to
    # a no-op so the paper run still works (just without per-sleeve gating).
    try:
        from src.research.quant_context import set_flow_enabled
    except Exception:  # noqa: BLE001 — flow gating is best-effort, never block the run
        logger.warning("run_once: quant_context.set_flow_enabled unavailable; flow gating disabled (no-op)", exc_info=True)

        def set_flow_enabled(_value: bool) -> None:
            return None

    summaries: dict[str, dict] = {}
    try:
        for sleeve_name in active_sleeves():
            try:
                # 0. Gate institutional-flow context for THIS sleeve's agent run.
                # Only scanner_agent_flow sees flow; scanner_agent (and the
                # non-agent sleeves) run flow-OFF. Set BEFORE compute_targets,
                # which is where the agent actually runs.
                set_flow_enabled(sleeve_name == "scanner_agent_flow")

                # 1. Targets this week (so we can pre-fetch their marks).
                targets = compute_targets(
                    sleeve_name,
                    scan_date,
                    run_scan_fn=run_scan_fn,
                    agent_fn=agent_fn,
                    factor_fn=factor_fn,
                    top_n=top_n,
                )
                # 2. Held tickers (open positions) from the DB.
                from app.backend.database.models import PaperPosition, PaperSleeve

                sleeve_row = session.query(PaperSleeve).filter_by(name=sleeve_name).one_or_none()
                held: list[str] = []
                if sleeve_row is not None:
                    held = [p.ticker for p in session.query(PaperPosition).filter_by(sleeve_id=sleeve_row.id, status="open").all()]

                # 3. Live marks for the union (held + target).
                universe = list(dict.fromkeys([*held, *targets]))
                prices: dict[str, float] = {}
                for ticker in universe:
                    px = price_fn(ticker)
                    if px is not None and px > 0:
                        prices[ticker] = px

                # 4. Reconstruct the broker at those marks and run the week.
                broker = reconstruct_broker(sleeve_name, session, prices=prices, starting_cash=starting_cash)
                # spy_benchmark is buy-and-hold: never age it out, else SPY churns
                # every hold_days and the A/B benchmark (graduation clause "sharpe >=
                # spy") becomes invalid.
                sleeve_hold_days = None if sleeve_name == "spy_benchmark" else hold_days
                summary = run_week(
                    sleeve_name=sleeve_name,
                    scan_date=scan_date,
                    week_key=week_key,
                    broker=broker,
                    session=session,
                    run_scan_fn=run_scan_fn,
                    agent_fn=agent_fn,
                    factor_fn=factor_fn,
                    top_n=top_n,
                    hold_days=sleeve_hold_days,
                    targets=targets,  # reuse step-1 targets — don't run scan/agent twice
                )
                summaries[sleeve_name] = summary
                logger.info(
                    "run_once: %s entered=%s exited=%s n_orders=%d cash=%.2f",
                    sleeve_name,
                    summary.get("entered"),
                    summary.get("exited"),
                    summary.get("n_orders"),
                    summary.get("cash_after"),
                )
            except Exception as exc:  # noqa: BLE001 — one bad sleeve must not sink the run
                logger.exception("run_once: sleeve %s failed", sleeve_name)
                summaries[sleeve_name] = {"error": f"{type(exc).__name__}: {exc}"}
    finally:
        # Restore the default so a paper run never leaves normal Analyze flow-OFF.
        set_flow_enabled(True)
    return summaries


# ---------------------------------------------------------------------------
# Zero-arg scheduler job callables (Task 8E).
# ---------------------------------------------------------------------------


def paper_weekly_job() -> None:
    """Weekly rebalance for all sleeves (scheduler/cron entrypoint).

    Self-contained: opens its own session, builds the live seams, derives the
    scan date (today) + week key, and runs. Swallows nothing structural but
    never lets a single sleeve abort the others (``run_once`` isolates them).
    Safe to retry — ``run_week`` is idempotent per ``(sleeve, week_key)``.
    """
    scan_date = date.today().isoformat()
    week_key = week_key_for(scan_date)
    run_scan_fn, agent_fn, factor_fn, price_fn, _ = _live_seams(universe=DEFAULT_UNIVERSE, model=DEFAULT_MODEL, provider=DEFAULT_PROVIDER)
    session = SessionLocal()
    try:
        summaries = run_once(
            session=session,
            run_scan_fn=run_scan_fn,
            agent_fn=agent_fn,
            price_fn=price_fn,
            factor_fn=factor_fn,
            scan_date=scan_date,
            week_key=week_key,
        )
        logger.info("paper_weekly_job: %s done; summaries=%s", week_key, summaries)
    finally:
        session.close()


def paper_daily_marks_job() -> None:
    """Daily mark-to-market for all sleeves (scheduler/cron entrypoint).

    Opens its own session, builds only the price seam (no scan/agent), and marks
    every sleeve for today. Idempotent — re-marking the same day overwrites that
    day's equity row.
    """
    scan_date = date.today().isoformat()
    from v2.data.factory import get_provider_factory

    provider_factory = get_provider_factory()

    def price_fn(ticker: str) -> float | None:
        return _latest_close(ticker, provider_factory, asof=scan_date)

    session = SessionLocal()
    try:
        results = mark_all(scan_date, session=session, price_fn=price_fn)
        logger.info("paper_daily_marks_job: %s marked %d sleeves", scan_date, len(results))
    finally:
        session.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.paper_trading.run",
        description="Paper-trading forward test: weekly rebalance, daily marks, report.",
    )
    parser.add_argument("--once", action="store_true", help="Run THIS week's rebalance for all sleeves.")
    parser.add_argument("--marks", action="store_true", help="Mark all sleeves to market for the scan date.")
    parser.add_argument("--report", action="store_true", help="Write the Markdown + HTML report to --out-dir.")
    parser.add_argument("--scan-date", default=None, help="As-of date YYYY-MM-DD (default: today).")
    parser.add_argument("--week-key", default=None, help="ISO week key YYYY-Www (default: derived from scan-date).")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help="Report output directory.")
    parser.add_argument("--universe", default=DEFAULT_UNIVERSE, help="Scanner universe kind.")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help="Ranked picks per scan.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Agent LLM model name.")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER, help="Agent LLM provider.")
    parser.add_argument("--hold-days", type=int, default=DEFAULT_HOLD_DAYS, help="Calendar-day hold window.")
    return parser


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = _build_parser().parse_args(argv)

    if not (args.once or args.marks or args.report):
        print("Nothing to do. Pass at least one of --once / --marks / --report.")
        return 2

    scan_date = args.scan_date or date.today().isoformat()
    week_key = args.week_key or week_key_for(scan_date)

    session = SessionLocal()
    try:
        # --once: weekly rebalance for all sleeves at live marks.
        if args.once:
            run_scan_fn, agent_fn, factor_fn, price_fn, universe_tickers = _live_seams(
                universe=args.universe,
                model=args.model,
                provider=args.provider,
            )
            print(f"[once] scan_date={scan_date} week_key={week_key} universe={args.universe} ({len(universe_tickers)} tickers)")
            summaries = run_once(
                session=session,
                run_scan_fn=run_scan_fn,
                agent_fn=agent_fn,
                price_fn=price_fn,
                factor_fn=factor_fn,
                scan_date=scan_date,
                week_key=week_key,
                top_n=args.top_n,
                hold_days=args.hold_days,
            )
            for sleeve_name, summary in summaries.items():
                if "error" in summary:
                    print(f"  {sleeve_name}: ERROR {summary['error']}")
                else:
                    print(f"  {sleeve_name}: entered={summary['entered']} exited={summary['exited']} n_orders={summary['n_orders']} cash={summary['cash_after']:.2f} already_ran={summary['already_ran']}")

        # --marks: daily mark-to-market for all sleeves at the scan date.
        if args.marks:
            from v2.data.factory import get_provider_factory

            provider_factory = get_provider_factory()

            def _price_fn(ticker: str) -> float | None:
                return _latest_close(ticker, provider_factory, asof=scan_date)

            results = mark_all(scan_date, session=session, price_fn=_price_fn)
            print(f"[marks] {scan_date}: marked {len(results)} sleeves")
            for sleeve_name, equity in results.items():
                print(f"  {sleeve_name}: equity={equity:.2f}")

        # --report: render Markdown + HTML to out-dir (no providers needed).
        if args.report:
            out = write_report(args.out_dir, session=session)
            print(f"[report] passed={out['passed']}")
            print(f"  md:   {out['report_md']}")
            print(f"  html: {out['report_html']}")
    finally:
        session.close()

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
