"""Verify the screener snapshot cron registers + dispatches builder + cleanup."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.backend.repositories.screener_repository import SnapshotRow


def test_constants_present():
    from app.backend.services.scheduler_service import (
        SCREENER_SNAPSHOT_CRON_EXPR,
        SCREENER_SNAPSHOT_JOB_ID,
    )
    assert SCREENER_SNAPSHOT_CRON_EXPR == "0 22 * * *"
    assert SCREENER_SNAPSHOT_JOB_ID == "screener_snapshot"


def test_run_snapshot_job_builds_both_markets_and_cleans_up():
    from app.backend.services import scheduler_service

    fake_us_rows = [
        SnapshotRow(ticker="AAPL", market="US", snapshot_date=date(2026, 5, 27))
    ]
    fake_cn_rows = [
        SnapshotRow(ticker="600519.SH", market="CN", snapshot_date=date(2026, 5, 27))
    ]
    fake_builder = MagicMock()
    fake_builder.build_for_universe.side_effect = [fake_us_rows, fake_cn_rows]
    fake_repo = MagicMock()
    fake_repo.bulk_upsert.return_value = 1
    fake_repo.cleanup_old_snapshots.return_value = 0
    fake_db = MagicMock()

    with patch.object(scheduler_service, "SessionLocal", return_value=fake_db), \
         patch.object(scheduler_service, "ScreenerRepository", return_value=fake_repo), \
         patch.object(scheduler_service, "SnapshotBuilder", return_value=fake_builder), \
         patch.object(scheduler_service, "AshareMetrics", return_value=MagicMock()):
        scheduler_service._run_snapshot_job_body()

    # Both markets dispatched in order
    calls = fake_builder.build_for_universe.call_args_list
    assert calls[0].args[0] == "US"
    assert calls[0].args[1] == "sp500"
    assert calls[1].args[0] == "CN"
    assert calls[1].args[1] == "csi300"

    # Upsert called twice (once per market)
    assert fake_repo.bulk_upsert.call_count == 2
    fake_repo.cleanup_old_snapshots.assert_called_once_with(keep_days=30)
    fake_db.close.assert_called_once()


def test_run_snapshot_job_us_failure_doesnt_block_cn():
    from app.backend.services import scheduler_service

    fake_builder = MagicMock()
    fake_builder.build_for_universe.side_effect = [
        RuntimeError("yfinance down"),
        [SnapshotRow(ticker="600519.SH", market="CN", snapshot_date=date(2026, 5, 27))],
    ]
    fake_repo = MagicMock()
    fake_repo.bulk_upsert.return_value = 1
    fake_repo.cleanup_old_snapshots.return_value = 0

    with patch.object(scheduler_service, "SessionLocal", return_value=MagicMock()), \
         patch.object(scheduler_service, "ScreenerRepository", return_value=fake_repo), \
         patch.object(scheduler_service, "SnapshotBuilder", return_value=fake_builder), \
         patch.object(scheduler_service, "AshareMetrics", return_value=MagicMock()):
        scheduler_service._run_snapshot_job_body()

    # CN still ran + upserted; cleanup still ran.
    assert fake_repo.bulk_upsert.call_count == 1
    fake_repo.cleanup_old_snapshots.assert_called_once()


def test_scheduler_registers_snapshot_job():
    """When SchedulerService starts, it adds the snapshot job via add_job."""
    from app.backend.services.scheduler_service import (
        SchedulerService,
        SCREENER_SNAPSHOT_JOB_ID,
    )

    fake_scanner = MagicMock()
    svc = SchedulerService(session_factory=MagicMock(),
                           scanner_service=fake_scanner)
    # Patch the scheduler's add_job so we don't actually launch APScheduler
    with patch.object(svc, "_scheduler") as fake_scheduler:
        fake_scheduler.get_jobs.return_value = []
        svc.start()

    job_ids = [c.kwargs.get("id") or (c.args[2] if len(c.args) >= 3 else None)
               for c in fake_scheduler.add_job.call_args_list]
    assert SCREENER_SNAPSHOT_JOB_ID in job_ids
