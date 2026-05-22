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
    @patch("app.backend.services.scheduler_service.SessionLocal")
    @patch("app.backend.services.scheduler_service.run_research")
    @patch("app.backend.services.scheduler_service.render_html")
    def test_runs_per_ticker_from_latest_pipeline_run(
        self, mock_render, mock_run, mock_session,
    ):
        """When the latest COMPLETE PipelineRun for today has tickers
        in its watchlist_json, the research job should run research
        once per ticker and persist each result."""
        from app.backend.services.scheduler_service import _run_research_job_body
        from src.research.models import (
            BacktestSummary, ResearchRequest, ResearchState, TradePlan,
        )

        mock_render.return_value = "<html></html>"
        mock_run.side_effect = lambda req: ResearchState(
            request=req,
            persona_assignments=None,
            module_results={},
            report_markdown="# r",
            strategy=TradePlan(
                direction="long", entry_price=145.0, target_price=165.0,
                stop_price=138.0, horizon_days=30, sizing_pct=0.05,
                confidence=72, rationale="r",
            ),
            backtest_summary=BacktestSummary(
                matches_found=0, win_rate=None, avg_pnl_pct=None,
                max_drawdown_pct=None, avg_holding_days=None,
                sample_quality="insufficient", caveat="x",
            ),
            rendered_html=None,
        )

        # Mock SessionLocal -> session -> repos
        db = MagicMock()
        mock_session.return_value = db

        # Latest PipelineRun stub with two tickers
        latest_pipeline_run = MagicMock()
        latest_pipeline_run.scan_date = "2026-05-22"
        latest_pipeline_run.watchlist_json = [
            {"ticker": "NVDA", "rank": 1},
            {"ticker": "AVGO", "rank": 2},
        ]

        with patch(
            "app.backend.services.scheduler_service.PipelineRunRepository"
        ) as mock_pipe_repo_cls, patch(
            "app.backend.services.scheduler_service.ResearchReportRepository"
        ) as mock_research_repo_cls:
            mock_pipe_repo = MagicMock()
            mock_pipe_repo.list_runs.return_value = [latest_pipeline_run]
            mock_pipe_repo_cls.return_value = mock_pipe_repo
            mock_research_repo = MagicMock()
            mock_research_repo_cls.return_value = mock_research_repo

            _run_research_job_body()

        # run_research called once per ticker
        assert mock_run.call_count == 2
        # Persisted both
        assert mock_research_repo.create_with_plan.call_count == 2

    @patch("app.backend.services.scheduler_service.SessionLocal")
    def test_no_recent_pipeline_run_skips_cleanly(self, mock_session):
        """When no legacy run exists for today, log + return without
        running research (Phase 3 v1 does not fall back to running its
        own scanner - that's a follow-up)."""
        from app.backend.services.scheduler_service import _run_research_job_body
        db = MagicMock()
        mock_session.return_value = db
        with patch(
            "app.backend.services.scheduler_service.PipelineRunRepository"
        ) as mock_pipe_repo_cls:
            mock_pipe_repo = MagicMock()
            mock_pipe_repo.list_runs.return_value = []
            mock_pipe_repo_cls.return_value = mock_pipe_repo
            _run_research_job_body()  # should not raise
