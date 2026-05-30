"""Repositories for scanner→agent pipeline persistence.

Mirrors the shape of ``ScanRunRepository``: sync, Session-injected, commit
per write, no business logic. Routes/services orchestrate.

Wave 4 (Task 4.3): ``PipelineRun`` reads are scoped by ``user_id`` for HTTP
routes (create stamps the owner). The lifecycle transitions
(mark_running/complete/error) stay unscoped — they're keyed by the unique
``run_id`` and only ever touch rows the system itself created.

``pipeline_schedule`` was a global singleton (id=1); it is now **per-user**:
each user gets their own row, created lazily on first GET. The legacy
unscoped ``get()`` accessor is retained for background/system callers (the
daily cron + the notification dispatcher's model-config lookup).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.backend.database.models import PipelineRun, PipelineSchedule


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
        user_id: Optional[int] = None,
    ) -> PipelineRun:
        """Insert a row in PENDING state. The background task flips it
        to RUNNING then COMPLETE/ERROR.

        ``user_id`` stamps the owner; HTTP routes pass the caller's id, the
        cron passes the seed owner's id (or None when none is resolvable)."""
        run = PipelineRun(
            id=run_id,
            scan_date=scan_date,
            template=template,
            selected_analysts=selected_analysts,
            top_n=top_n,
            universe=universe,
            status="PENDING",
            user_id=user_id,
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

    def get_by_id(self, run_id: str, *, user_id: Optional[int] = None) -> Optional[PipelineRun]:
        """Get a run by id. When ``user_id`` is provided (HTTP routes), the
        lookup is scoped — a cross-tenant id returns None (route → 404).

        Background callers (the cron's lifecycle transitions) omit ``user_id``
        and look up by the unique run_id alone."""
        q = self.db.query(PipelineRun).filter(PipelineRun.id == run_id)
        if user_id is not None:
            q = q.filter(PipelineRun.user_id == user_id)
        return q.first()

    def list_runs(
        self,
        *,
        user_id: Optional[int] = None,
        limit: int = 50,
        template: str | None = None,
        status: str | None = None,
        since: str | None = None,
    ) -> list[PipelineRun]:
        """List runs newest-first. Filters all optional + ANDed together.

        When ``user_id`` is provided, only that user's runs are returned."""
        q = self.db.query(PipelineRun)
        if user_id is not None:
            q = q.filter(PipelineRun.user_id == user_id)
        if template:
            q = q.filter(PipelineRun.template == template)
        if status:
            q = q.filter(PipelineRun.status == status)
        if since:
            q = q.filter(PipelineRun.scan_date >= since)
        return q.order_by(desc(PipelineRun.created_at)).limit(limit).all()


_SCHEDULE_FIELDS = {"enabled", "top_n", "template", "universe", "model_name", "model_provider"}


class PipelineScheduleRepository:
    """Per-user ``pipeline_schedule`` rows (one per user, lazily created).

    HTTP routes call the ``*_for_user`` methods. The legacy unscoped
    ``get()`` is retained for background/system callers (the daily cron and
    the notification dispatcher, which only read model_name/model_provider)."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # -- unscoped (background / system use only) -----------------------------

    def get(self) -> Optional[PipelineSchedule]:
        """Return *a* schedule row for system use, lowest id first.

        Used by the notification dispatcher (model-config lookup, with a
        ``None`` fallback) and as the cron's fallback when no seed owner is
        resolvable. Returns ``None`` when no schedule row exists at all."""
        return self.db.query(PipelineSchedule).order_by(PipelineSchedule.id.asc()).first()

    # -- scoped (HTTP routes) ------------------------------------------------

    def get_for_user(self, user_id: int) -> Optional[PipelineSchedule]:
        """Return the caller's schedule row, or ``None`` if not yet created."""
        return self.db.query(PipelineSchedule).filter(PipelineSchedule.user_id == user_id).first()

    def get_or_create_for_user(self, user_id: int) -> PipelineSchedule:
        """Return the caller's schedule row, creating one with defaults on
        first access (cron ships OFF by default — see the model)."""
        row = self.get_for_user(user_id)
        if row is None:
            row = PipelineSchedule(user_id=user_id)
            self.db.add(row)
            self.db.commit()
            self.db.refresh(row)
        return row

    def update_for_user(self, user_id: int, **fields: Any) -> PipelineSchedule:
        """Partial update of the caller's row (get-or-create first). Unknown
        keys ignored (caller already validated via Pydantic)."""
        row = self.get_or_create_for_user(user_id)
        for k, v in fields.items():
            if k in _SCHEDULE_FIELDS and v is not None:
                setattr(row, k, v)
        self.db.commit()
        self.db.refresh(row)
        return row
