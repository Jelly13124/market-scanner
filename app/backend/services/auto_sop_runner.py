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
import time
from datetime import date

from sqlalchemy.orm import Session

from app.backend.database.models import WatchlistEntry
from app.backend.repositories.research_repository import ResearchReportRepository
from src.research.html_render import render_sop
from src.research.models import AnalyzeRequest, SECTION_ORDER
from src.research.sop_orchestrator import run_sop

logger = logging.getLogger(__name__)


def run_auto_sop_for_scan(
    db: Session,
    scan_run_id: int,
    top_n: int,
    use_personas: bool,
    *,
    owner_user_id: int | None = None,
) -> list[int]:
    """Run SOP on top-N watchlist entries for ``scan_run_id``.

    Returns the list of newly-inserted ``ResearchReport.id`` values, in
    the same rank order the tickers were processed. Empty input / N=0
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

    for entry in entries:
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
            report = run_sop(req)
        except Exception as e:
            logger.exception("auto_sop: run_sop failed for %s: %s", ticker, e)
            continue
        duration = time.monotonic() - t0

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
