"""Scheduled report delivery (Stage 3): run the SOP for a set of tickers on a
cron and email each rendered report to the user's verified recipients.

Owner-scoped CRUD; every mutation (un)registers the APScheduler cron via
SchedulerService so changes take effect without a restart.
"""
import logging
from datetime import datetime

from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.backend.auth.dependencies import get_current_user
from app.backend.database import get_db
from app.backend.database.models import ReportSchedule, User
from app.backend.services.scheduler_service import SchedulerService, get_scheduler_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/report-schedules", tags=["report-schedules"])

_MAX_SCHEDULES = 5
_MAX_TICKERS = 10


def _validate_cron(expr: str) -> None:
    try:
        CronTrigger.from_crontab(expr, timezone="America/New_York")
    except (ValueError, TypeError) as e:
        raise HTTPException(400, f"Invalid schedule (cron {expr!r}): {e}")


def _norm_tickers(tickers: list[str]) -> list[str]:
    out: list[str] = []
    for t in tickers or []:
        t = (t or "").strip().upper()
        if t and t not in out:
            out.append(t)
    if not out:
        raise HTTPException(400, "At least one ticker is required")
    if len(out) > _MAX_TICKERS:
        raise HTTPException(400, f"At most {_MAX_TICKERS} tickers per schedule")
    return out


def _norm_lang(lang: str | None) -> str:
    return lang if lang in ("en", "zh") else "en"


class ScheduleCreate(BaseModel):
    tickers: list[str]
    cron_expr: str
    report_language: str = "en"
    is_enabled: bool = True


class ScheduleUpdate(BaseModel):
    tickers: list[str] | None = None
    cron_expr: str | None = None
    report_language: str | None = None
    is_enabled: bool | None = None


class ScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tickers: list[str]
    cron_expr: str
    report_language: str
    is_enabled: bool
    last_run_at: datetime | None
    created_at: datetime


@router.get("/", response_model=list[ScheduleOut])
def list_schedules(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ReportSchedule]:
    return (
        db.query(ReportSchedule)
        .filter(ReportSchedule.user_id == current_user.id)
        .order_by(ReportSchedule.id)
        .all()
    )


@router.post("/", response_model=ScheduleOut, status_code=201)
def create_schedule(
    body: ScheduleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scheduler: SchedulerService = Depends(get_scheduler_service),
) -> ReportSchedule:
    if db.query(ReportSchedule).filter(ReportSchedule.user_id == current_user.id).count() >= _MAX_SCHEDULES:
        raise HTTPException(400, f"At most {_MAX_SCHEDULES} schedules per account")
    _validate_cron(body.cron_expr)
    tickers = _norm_tickers(body.tickers)
    sched = ReportSchedule(
        user_id=current_user.id,
        tickers=tickers,
        cron_expr=body.cron_expr,
        report_language=_norm_lang(body.report_language),
        is_enabled=body.is_enabled,
    )
    db.add(sched)
    db.commit()
    db.refresh(sched)
    try:
        scheduler.register_report_schedule(sched)
    except Exception as e:
        logger.warning("register report schedule %s failed: %s", sched.id, e)
    return sched


@router.patch("/{schedule_id}", response_model=ScheduleOut)
def update_schedule(
    schedule_id: int,
    body: ScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scheduler: SchedulerService = Depends(get_scheduler_service),
) -> ReportSchedule:
    sched = db.query(ReportSchedule).filter(
        ReportSchedule.id == schedule_id, ReportSchedule.user_id == current_user.id
    ).first()
    if not sched:
        raise HTTPException(404, "Schedule not found")
    if body.cron_expr is not None:
        _validate_cron(body.cron_expr)
        sched.cron_expr = body.cron_expr
    if body.tickers is not None:
        sched.tickers = _norm_tickers(body.tickers)
    if body.report_language is not None:
        sched.report_language = _norm_lang(body.report_language)
    if body.is_enabled is not None:
        sched.is_enabled = body.is_enabled
    db.commit()
    db.refresh(sched)
    # register_report_schedule re-registers when enabled, unregisters when not.
    try:
        scheduler.register_report_schedule(sched)
    except Exception as e:
        logger.warning("re-register report schedule %s failed: %s", sched.id, e)
    return sched


@router.delete("/{schedule_id}", status_code=204)
def delete_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scheduler: SchedulerService = Depends(get_scheduler_service),
) -> None:
    sched = db.query(ReportSchedule).filter(
        ReportSchedule.id == schedule_id, ReportSchedule.user_id == current_user.id
    ).first()
    if not sched:
        raise HTTPException(404, "Schedule not found")
    db.delete(sched)
    db.commit()
    try:
        scheduler.unregister_report_schedule(schedule_id)
    except Exception as e:
        logger.warning("unregister report schedule %s failed: %s", schedule_id, e)
