"""Phase 5E: after a scan completes, run SOP on top-N tickers and
emit a bundled email.

Loads the top-N WatchlistEntry rows by rank for a given scan_run_id, runs
the full SOP pipeline per ticker, persists each report (Phase 4's
``create_analyze`` path), and returns the list of newly-created
``ResearchReport.id`` values. The caller (ScannerService) then hands
that id list to the notification dispatcher's bundled-email path.

Failures are isolated per-ticker: one ticker raising won't abort the
loop — subsequent tickers still run. An empty input or ``top_n=0``
short-circuits to ``[]``.
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from sqlalchemy.orm import Session

from app.backend.database.models import WatchlistEntry
from app.backend.repositories.research_repository import ResearchReportRepository
from src.research.html_render import render_sop
from src.research.models import AnalyzeRequest, SECTION_ORDER
from src.research.sop_orchestrator import run_sop

logger = logging.getLogger(__name__)

# How many tickers to analyze concurrently in the post-scan Top-N batch.
# Each ticker's run_sop ALREADY fans its sections out across up to
# SOP_MAX_PARALLEL threads (default 10), so peak LLM concurrency is roughly
# AUTO_SOP_MAX_WORKERS * SOP_MAX_PARALLEL. Keep this modest so a free-tier
# provider key isn't rate-limited; raise it if your plan has the headroom.
_MAX_WORKERS = max(1, int(os.environ.get("AUTO_SOP_MAX_WORKERS", "3")))


def run_auto_sop_for_scan(
    db: Session,
    scan_run_id: int,
    top_n: int,
    use_personas: bool,
    *,
    owner_user_id: int | None = None,
) -> list[int]:
    """Run SOP on top-N watchlist entries for ``scan_run_id``.

    The per-ticker analyses run CONCURRENTLY (bounded by AUTO_SOP_MAX_WORKERS);
    rendering + persistence then happen sequentially on this thread, so the
    returned ``ResearchReport.id`` list stays in rank order. Empty input / N=0
    returns ``[]`` without touching the LLM.
    """
    if top_n <= 0:
        return []

    entries = (
        db.query(WatchlistEntry)
        .filter(WatchlistEntry.scan_run_id == scan_run_id)
        .order_by(WatchlistEntry.rank.asc())
        .limit(top_n)
        .all()
    )
    if not entries:
        logger.warning(
            "auto_sop: no watchlist entries for scan_run %s", scan_run_id,
        )
        return []

    repo = ResearchReportRepository(db)
    report_ids: list[int] = []
    today_iso = date.today().isoformat()

    # Per-user keys: run the SOP with the config OWNER's stored provider keys.
    # The scanner cron runs detached from any HTTP request, so there is no
    # current_user — without this, run_sop falls back to host env keys, which on
    # the per-user-key deploy are ABSENT → "no API key". Mirrors the
    # /research/analyze route and the report-schedule cron.
    api_keys = None
    if owner_user_id is not None:
        try:
            from app.backend.services.api_key_service import ApiKeyService

            api_keys = ApiKeyService(db, owner_user_id).get_api_keys_dict()
        except Exception:
            logger.exception("auto_sop: failed to load keys for user %s", owner_user_id)

    # ---- Phase 1: analyze every ticker CONCURRENTLY (DB-free) ----
    # run_sop is thread-safe — FastAPI already calls it concurrently across
    # requests, and it threads api_keys via SectionContext (never globals). It
    # touches NO database. Fan the tickers out across a bounded pool, then
    # render + persist back on THIS thread (a SQLAlchemy Session is
    # single-thread-only). Peak LLM concurrency ~= workers * SOP_MAX_PARALLEL.
    def _analyze(entry):
        ticker = entry.ticker
        req = AnalyzeRequest(
            ticker=ticker,
            objective="medium_term",
            position_budget_usd=None,
            already_holds=False,
            cost_basis_usd=None,
            risk_tolerance="balanced",
            use_personas=use_personas,
            included_sections=set(SECTION_ORDER),
        )
        t0 = time.monotonic()
        try:
            report = run_sop(req, api_keys=api_keys)
        except Exception as e:
            logger.exception("auto_sop: run_sop failed for %s: %s", ticker, e)
            return None
        return report, time.monotonic() - t0

    workers = min(len(entries), _MAX_WORKERS)
    logger.info(
        "auto_sop: analyzing %d ticker(s) (workers=%d) for scan_run %s",
        len(entries), workers, scan_run_id,
    )
    # Index results by rank so Phase 2 persists in rank order (entries is
    # rank-asc), no matter what order the concurrent analyses finish in.
    analyzed: list = [None] * len(entries)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="auto-sop") as pool:
        future_to_idx = {pool.submit(_analyze, e): i for i, e in enumerate(entries)}
        for fut in as_completed(future_to_idx):
            idx = future_to_idx[fut]
            analyzed[idx] = fut.result()
            # Per-ticker completion log — the natural hook for a future
            # analyze-progress side panel to surface live progress.
            if analyzed[idx] is not None:
                logger.info(
                    "auto_sop: %s analysis done (%.1fs)",
                    entries[idx].ticker, analyzed[idx][1],
                )

    # ---- Phase 2: render + persist SEQUENTIALLY on the main thread ----
    # Single DB Session; rank order preserved. render_sop emits chart URLs
    # (no matplotlib here), so this is cheap next to the analyses above.
    for entry, result in zip(entries, analyzed):
        if result is None:
            continue
        report, duration = result
        ticker = entry.ticker

        try:
            html = render_sop(report, report_id=None)
            report["rendered_html"] = html
        except Exception as e:
            logger.exception("auto_sop: render failed for %s: %s", ticker, e)
            continue

        arq_dict = {
            "ticker": ticker,
            "objective": "medium_term",
            "position_budget_usd": None,
            "already_holds": False,
            "cost_basis_usd": None,
            "risk_tolerance": "balanced",
            "use_personas": use_personas,
            "included_sections": sorted(set(SECTION_ORDER)),
        }
        sections_json = {
            name: {
                "markdown": p.markdown,
                "structured": p.structured,
                "skipped": p.skipped,
                "persona_used": p.persona_used,
                "skip_reason": p.skip_reason,
            }
            for name, p in (report.get("sections") or {}).items()
            if not name.startswith("_")
        }
        report_markdown = "\n\n".join(
            p.markdown for name, p in (report.get("sections") or {}).items()
            if not name.startswith("_")
        )

        try:
            row = repo.create_analyze(
                report={
                    "ticker": ticker,
                    "scan_date": today_iso,
                    "request_json": arq_dict,
                    "report_markdown": report_markdown,
                    "rendered_html": html,
                    "use_personas": use_personas,
                    "persona_assignments_json": report.get("persona_assignments"),
                    "duration_seconds": duration,
                    "analyze_request_json": arq_dict,
                    "sections_json": sections_json,
                },
                user_id=owner_user_id,
            )
        except Exception as e:
            logger.exception("auto_sop: persist failed for %s: %s", ticker, e)
            continue

        # Re-render with the freshly-allocated report id so the K-line
        # chart <img> tags resolve to the right /research/reports/{id}/chart
        # URLs (matches the Phase 4 trigger_analyze pattern).
        try:
            final_html = render_sop(report, report_id=row.id)
            row.rendered_html = final_html
            db.commit()
        except Exception as e:
            logger.exception(
                "auto_sop: re-render with id failed for %s: %s", ticker, e,
            )

        report_ids.append(row.id)
        logger.info(
            "auto_sop: persisted report id=%s ticker=%s (%.1fs)",
            row.id, ticker, duration,
        )

    return report_ids
