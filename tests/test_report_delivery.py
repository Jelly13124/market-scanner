"""report_delivery.email_report_html — delivers the report as an HTML attachment."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database.models import Base, ReportRecipient


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed_recipient(session, *, user_id=1, email="me@example.com", verified=True):
    r = ReportRecipient(user_id=user_id, email=email, is_verified=verified)
    session.add(r)
    session.commit()
    return r


class TestEmailReportAttachment:
    @patch("app.backend.services.report_delivery.EmailHandler")
    def test_full_report_rides_as_html_attachment_not_inline(
        self, mock_handler_cls, db_session,
    ):
        from app.backend.services.report_delivery import email_report_html

        _seed_recipient(db_session, user_id=1, email="me@example.com")
        inst = MagicMock()
        inst.send.return_value = {"status": "ok"}
        mock_handler_cls.return_value = inst

        report_html = "<html><body><h1>NVDA full report body</h1></body></html>"
        res = email_report_html(db_session, 1, ticker="NVDA", html=report_html)

        assert res == {"sent": ["me@example.com"], "failed": []}
        kwargs = inst.send.call_args.kwargs
        # The full report is NOT inlined in the body...
        assert "full report body" not in kwargs["html"]
        assert "full report body" not in kwargs["text"]
        # ...it rides as a base64 .html attachment that decodes back verbatim.
        atts = kwargs["attachments"]
        assert len(atts) == 1
        assert atts[0]["filename"] == "NVDA_report.html"
        decoded = base64.b64decode(atts[0]["content"]).decode("utf-8")
        assert decoded == report_html

    @patch("app.backend.services.report_delivery.EmailHandler")
    def test_unverified_recipient_is_quiet_noop(self, mock_handler_cls, db_session):
        from app.backend.services.report_delivery import email_report_html

        _seed_recipient(db_session, user_id=1, email="me@example.com", verified=False)
        inst = MagicMock()
        mock_handler_cls.return_value = inst

        res = email_report_html(db_session, 1, ticker="NVDA", html="<html></html>")
        assert res == {"sent": [], "failed": []}
        inst.send.assert_not_called()
