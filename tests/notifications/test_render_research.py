"""Render path for research-report emails. Mirrors the pipeline render
tests' structure."""

from __future__ import annotations

from types import SimpleNamespace
from datetime import datetime


def _make_report():
    return SimpleNamespace(
        id=1,
        ticker="NVDA",
        scan_date="2026-05-22",
        created_at=datetime(2026, 5, 22, 16, 35),
        use_personas=True,
        duration_seconds=42.5,
        rendered_html=(
            "<html><body><h1>NVDA</h1><p>Body content here.</p></body></html>"
        ),
        report_markdown="# NVDA\n\nBody content here.",
    )


class TestRenderResearchHtml:
    def test_returns_the_pre_rendered_html_when_present(self):
        from app.backend.services.notifications.render import render_research_html
        report = _make_report()
        html = render_research_html(report)
        assert isinstance(html, str)
        assert "NVDA" in html

    def test_fallback_when_html_missing(self):
        from app.backend.services.notifications.render import render_research_html
        report = _make_report()
        report.rendered_html = ""
        html = render_research_html(report)
        assert "<html>" in html.lower()
        assert "NVDA" in html


class TestRenderResearchText:
    def test_extracts_plain_text_from_markdown(self):
        from app.backend.services.notifications.render import render_research_text
        report = _make_report()
        text = render_research_text(report)
        assert "NVDA" in text
        assert "Body content here." in text
        # No HTML tags
        assert "<" not in text
