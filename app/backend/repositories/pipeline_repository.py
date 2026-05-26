"""Repositories for scanner→agent pipeline persistence.

Mirrors the shape of ``ScanRunRepository``: sync, Session-injected, commit
per write, no business logic. Routes/services orchestrate.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.backend.database.models import PipelineRun, PipelineSchedule


# Hard-coded singleton row id for the daily schedule config. The
# pipeline_schedule table only ever holds one row; using a fixed id is
# simpler than an unenforced "only one row" invariant.
_SCHEDULE_ID = 1


class PipelineRunRepository:
    """CRUD + lifecycle transitions for ``PipelineRun``."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # -- create --------------------------------------------------------------

    def create_pending(
        self,
        *,
        run_id: str,
        scan_date: str,
        template: str,
        selected_analysts: list[str],
        top_n: int,
        universe: str,
    ) -> PipelineRun:
        """Insert a row in PENDING state. The background task flips it
        to RUNNING then COMPLETE/ERROR."""
        run = PipelineRun(
            id=run_id,
            scan_date=scan_date,
            template=template,
            selected_analysts=selected_analysts,
            top_n=top_n,
            universe=universe,
            status="PENDING",
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    # -- lifecycle ----------------------------------------------------------

    def mark_running(self, run_id: str) -> Optional[PipelineRun]:
        run = self.get_by_id(run_id)
        if not run:
            return None
        run.status = "RUNNING"
        run.started_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(run)
        return run

    def mark_complete(
        self,
        run_id: str,
        *,
        watchlist: list[dict],
        agent_decisions: dict,
        analyst_signals: dict,
        duration_seconds: float,
    ) -> Optional[PipelineRun]:
        run = self.get_by_id(run_id)
        if not run:
            return None
        run.status = "COMPLETE"
        run.completed_at = datetime.utcnow()
        run.watchlist_json = watchlist
        run.agent_decisions_json = agent_decisions
        run.analyst_signals_json = analyst_signals
        run.duration_seconds = duration_seconds
        self.db.commit()
        self.db.refresh(run)
        return run

    def mark_error(self, run_id: str, error: str) -> Optional[PipelineRun]:
        run = self.get_by_id(run_id)
        if not run:
            return None
        run.status = "ERROR"
        run.completed_at = datetime.utcnow()
        run.error = error[:5000]  # cap so a giant traceback doesn't bloat DB
        self.db.commit()
        self.db.refresh(run)
        return run

    # -- read ---------------------------------------------------------------

    def get_by_id(self, run_id: str) -> Optional[PipelineRun]:
        return self.db.query(PipelineRun).filter(PipelineRun.id == run_id).first()

    def list_runs(
        self,
        *,
        limit: int = 50,
        template: str | None = None,
        status: str | None = None,
        since: str | None = None,
    ) -> list[PipelineRun]:
        """List runs newest-first. Filters all optional + ANDed together."""
        q = self.db.query(PipelineRun)
        if template:
            q = q.filter(PipelineRun.template == template)
        if status:
            q = q.filter(PipelineRun.status == status)
        if since:
            q = q.filter(PipelineRun.scan_date >= since)
        return q.order_by(desc(PipelineRun.created_at)).limit(limit).all()


class PipelineScheduleRepository:
    """Get/upsert the single ``pipeline_schedule`` row."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self) -> Optional[PipelineSchedule]:
        """Return the singleton row. Will return ``None`` only if the
        seed migration hasn't run — caller should treat that as a hard
        configuration error."""
        return (
            self.db.query(PipelineSchedule)
            .filter(PipelineSchedule.id == _SCHEDULE_ID)
            .first()
        )

    def update(self, **fields: Any) -> PipelineSchedule:
        """Partial update of the singleton. Unknown keys are ignored
        (caller already validated via Pydantic)."""
        row = self.get()
        if not row:
            # Defensive: if seed didn't run for some reason, create the
            # row with all defaults so we don't 500 out of the route.
            row = PipelineSchedule(id=_SCHEDULE_ID)
            self.db.add(row)
        allowed = {"enabled", "top_n", "template", "universe",
                   "model_name", "model_provider"}
        for k, v in fields.items():
            if k in allowed and v is not None:
                setattr(row, k, v)
        self.db.commit()
        self.db.refresh(row)
        return row
