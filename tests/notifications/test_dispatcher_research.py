"""Dispatcher should route 'research.completed' events to the
research render path and call the email/webhook handler with that
HTML body."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest


def _make_report():
    from datetime import datetime
    return SimpleNamespace(
        id=42,
        ticker="NVDA",
        scan_date="2026-05-22",
        created_at=datetime(2026, 5, 22, 16, 35),
        rendered_html="<html><body>NVDA body</body></html>",
        report_markdown="# NVDA\n\nBody.",
    )


class TestDispatchResearchEvent:
    @patch("app.backend.services.notifications.dispatcher.render_research_html")
    @patch("app.backend.services.notifications.dispatcher.render_research_text")
    def test_dispatch_uses_research_render(self, mock_text, mock_html):
        """When event_type='research.completed', dispatcher should pull the
        research-render functions, not the pipeline ones."""
        from app.backend.services.notifications.dispatcher import (
            NotificationDispatcher,
        )
        mock_html.return_value = "<html>NVDA</html>"
        mock_text.return_value = "NVDA"

        # Stub out everything but the render-routing logic
        mock_session_factory = MagicMock()
        d = NotificationDispatcher(mock_session_factory)

        # The dispatcher exposes a method that builds the email body for
        # a given event_type + run object. Test that the research event
        # routes to research render.
        body_html, body_text = d._render_for_event(
            event_type="research.completed",
            run=_make_report(),
        )
        assert body_html == "<html>NVDA</html>"
        assert body_text == "NVDA"
        mock_html.assert_called_once()
        mock_text.assert_called_once()
