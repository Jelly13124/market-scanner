"""Phase 5E: bundled-email render tests.

Three tests on the HTML body shape:
  1. Master index links to each ticker's <details> anchor.
  2. Each report's HTML appears wrapped as a collapsible <details>.
  3. Plain-text alt enumerates all tickers.
"""

from __future__ import annotations

from types import SimpleNamespace


def _make_report(rid: int, ticker: str, body: str = "Report body") -> SimpleNamespace:
    return SimpleNamespace(
        id=rid,
        ticker=ticker,
        scan_date="2026-05-24",
        rendered_html=f"<html><body><h1>{ticker}</h1><p>{body}</p></body></html>",
        report_markdown=f"# {ticker}\n\n{body}",
    )


class TestRenderBundledResearchHtml:
    def test_contains_master_index_with_ticker_anchors(self):
        from app.backend.services.notifications.bundled_email import (
            render_bundled_research_html,
        )
        reports = [
            _make_report(1, "NVDA"),
            _make_report(2, "AAPL"),
            _make_report(3, "MSFT"),
        ]
        html = render_bundled_research_html(reports)

        # Index section is present
        assert "Index" in html
        assert "Daily SOP Reports" in html
        # Per-ticker anchor links in the index
        assert 'href="#ticker-1"' in html
        assert 'href="#ticker-2"' in html
        assert 'href="#ticker-3"' in html
        # Header reflects ticker count
        assert "3 tickers" in html

    def test_each_report_rendered_as_collapsible_details_block(self):
        from app.backend.services.notifications.bundled_email import (
            render_bundled_research_html,
        )
        reports = [
            _make_report(10, "NVDA", body="bullish thesis"),
            _make_report(11, "TSLA", body="growth story"),
        ]
        html = render_bundled_research_html(reports)

        # One <details> block per ticker, each with an id matching the
        # index anchor and a <summary> containing the ticker.
        assert '<details id="ticker-10"' in html
        assert '<details id="ticker-11"' in html
        assert "<summary" in html
        assert ">NVDA</summary>" in html
        assert ">TSLA</summary>" in html
        # Inner body content (from the report HTML, unwrapped from
        # <html><body>) appears in the bundled doc.
        assert "bullish thesis" in html
        assert "growth story" in html

    def test_empty_reports_returns_safe_placeholder(self):
        from app.backend.services.notifications.bundled_email import (
            render_bundled_research_html,
        )
        html = render_bundled_research_html([])
        assert "No reports produced" in html


class TestRenderBundledResearchText:
    def test_plain_text_lists_every_ticker(self):
        from app.backend.services.notifications.bundled_email import (
            render_bundled_research_text,
        )
        reports = [
            _make_report(1, "NVDA"),
            _make_report(2, "AAPL"),
            _make_report(3, "MSFT"),
        ]
        text = render_bundled_research_text(reports)
        assert "NVDA" in text
        assert "AAPL" in text
        assert "MSFT" in text
        assert "3 tickers" in text
        # No HTML markup in the plain-text alt
        assert "<" not in text
