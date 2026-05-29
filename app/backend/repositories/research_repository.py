"""Repository for the research pipeline persistence layer.

Mirrors the shape of PipelineRunRepository: sync, Session-injected,
commit per write, no business logic. Routes/services orchestrate.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.backend.database.models import ResearchReport, ResearchTradePlan


class ResearchReportRepository:
    """CRUD for ResearchReport + 1-to-1 ResearchTradePlan."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # -- create --------------------------------------------------------------

    def create_with_plan(
        self,
        *,
        report: dict,
        plan: dict,
    ) -> ResearchReport:
        """Insert a ResearchReport AND its paired ResearchTradePlan in one
        commit. Caller passes plan dict with report_id=0 placeholder; we
        overwrite with the real FK after the report inserts.
        """
        # Strip placeholder FK from the plan dict; we set it after the
        # report id is allocated.
        plan_kwargs = dict(plan)
        plan_kwargs.pop("report_id", None)

        report_row = ResearchReport(**report)
        self.db.add(report_row)
        self.db.flush()  # populate report_row.id without committing yet

        plan_row = ResearchTradePlan(report_id=report_row.id, **plan_kwargs)
        self.db.add(plan_row)
        self.db.commit()
        self.db.refresh(report_row)
        return report_row

    def create_analyze(
        self,
        *,
        report: dict,
    ) -> ResearchReport:
        """Phase 4: insert a ResearchReport WITHOUT a paired TradePlan.

        Phase 4 SOP runs don't produce a single-shot TradePlan — the
        actionable strategy lives in the final_strategy section
        markdown and the risk_position section. So we leave the
        research_trade_plans row absent.
        """
        report_row = ResearchReport(**report)
        self.db.add(report_row)
        self.db.commit()
        self.db.refresh(report_row)
        return report_row

    # -- read ---------------------------------------------------------------

    def get_by_id(self, report_id: int) -> Optional[ResearchReport]:
        return (
            self.db.query(ResearchReport)
            .filter(ResearchReport.id == report_id)
            .first()
        )

    def get_plan_for_report(self, report_id: int) -> Optional[ResearchTradePlan]:
        return (
            self.db.query(ResearchTradePlan)
            .filter(ResearchTradePlan.report_id == report_id)
            .first()
        )

    def list_reports(
        self,
        *,
        ticker: str | None = None,
        scan_date: str | None = None,
        limit: int = 50,
    ) -> list[ResearchReport]:
        """List reports newest-first. ticker + scan_date filters AND together."""
        q = self.db.query(ResearchReport)
        if ticker:
            q = q.filter(ResearchReport.ticker == ticker)
        if scan_date:
            q = q.filter(ResearchReport.scan_date == scan_date)
        return q.order_by(desc(ResearchReport.created_at), desc(ResearchReport.id)).limit(limit).all()

    # -- delete -------------------------------------------------------------

    def delete(self, report_id: int) -> bool:
        """Delete a report (and its paired trade plan, if any). Returns
        False when the report doesn't exist."""
        report = self.get_by_id(report_id)
        if report is None:
            return False
        # Phase 1-3 reports have a 1-to-1 ResearchTradePlan via report_id;
        # Phase 4 SOP reports don't. Remove any plan first to avoid an FK
        # constraint error.
        self.db.query(ResearchTradePlan).filter(
            ResearchTradePlan.report_id == report_id
        ).delete()
        self.db.delete(report)
        self.db.commit()
        return True
