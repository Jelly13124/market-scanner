"""Tests for ResearchReportRepository.delete.

Covers:
- create → delete → gone (returns True, get_by_id returns None)
- delete missing id → False
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backend.database.connection import Base
from app.backend.repositories.research_repository import ResearchReportRepository


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    try:
        yield sess
    finally:
        sess.close()
        engine.dispose()


def _analyze_report_kwargs(ticker="TSLA"):
    """Minimal valid kwargs for create_analyze (no ResearchTradePlan needed)."""
    return dict(
        ticker=ticker,
        scan_date="2026-05-28",
        request_json={"ticker": ticker},
        report_markdown="# Report",
        rendered_html="<html></html>",
        use_personas=False,
        persona_assignments_json=None,
        duration_seconds=5.0,
        analyze_request_json={"ticker": ticker, "objective": "general_research"},
        sections_json={},
    )


_UID = 1  # stable fake user_id for repo unit tests


class TestResearchReportDelete:
    def test_delete_existing_returns_true_and_row_gone(self, db_session):
        repo = ResearchReportRepository(db_session)
        row = repo.create_analyze(report=_analyze_report_kwargs(), user_id=_UID)
        report_id = row.id
        assert report_id is not None

        result = repo.delete(report_id, user_id=_UID)

        assert result is True
        assert repo.get_by_id(report_id, user_id=_UID) is None

    def test_delete_missing_returns_false(self, db_session):
        repo = ResearchReportRepository(db_session)
        result = repo.delete(999999, user_id=_UID)
        assert result is False

    def test_delete_idempotent_second_call_returns_false(self, db_session):
        """Deleting the same id twice: first True, second False."""
        repo = ResearchReportRepository(db_session)
        row = repo.create_analyze(report=_analyze_report_kwargs("NVDA"), user_id=_UID)
        report_id = row.id

        assert repo.delete(report_id, user_id=_UID) is True
        assert repo.delete(report_id, user_id=_UID) is False
