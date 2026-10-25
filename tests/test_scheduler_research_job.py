"""SchedulerService should register a research cron at 16:35 ET and
the job body should: fetch latest legacy PipelineRun watchlist for
today, run research per ticker, persist reports."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from app.backend.services.scheduler_service import (
    RESEARCH_CRON_EXPR,
)


def test_research_cron_expression_is_4_35pm_weekdays():
    """4:35pm ET, Monday-Friday."""
    assert RESEARCH_CRON_EXPR == "35 16 * * 1-5"


class TestResearchJobBody:
    @patch('app.backend.services.scheduler_service.run_research')
    @patch('app.backend.services.scheduler_service.SessionLocal')
    def test_stale_legacy_callback_does_not_run_research(self, session, run):
        from app.backend.services.scheduler_service import _run_research_job_body
        _run_research_job_body()
        run.assert_not_called()
        session.assert_not_called()
