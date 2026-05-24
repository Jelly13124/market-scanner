"""Phase 5E: bundled-email helpers — render N research reports as one
email body with a master index + collapsible per-ticker sections.

Why collapsible: each SOP report is ~50KB of HTML. Five reports = 250KB
which exceeds Gmail's ~102KB "show full message" clip threshold. The
master index gives the reader a one-line-per-ticker overview at the top
so the email is still useful even after Gmail clips the rest; the
``<details>`` blocks keep each report self-contained so when the user
hits "show full message" they can drill into one ticker at a time.

Inner HTML for each report goes through ``render_research_html`` so the
Phase 5A K-line-image-stripping logic still applies.
"""

from __future__ import annotations

import html as _html


def render_bundled_research_html(reports: list) -> str:
    """Render N ``ResearchReport`` rows as one bundled HTML email body.

    Each report's pre-rendered HTML is unwrapped from its ``<html><body>``
    envelope so the bundled document stays a single valid HTML doc.
    """
    from app.backend.services.notifications.render import render_research_html

    if not reports:
        return "<html><body><p>No reports produced.</p></body></html>"

    index_items: list[str] = []
    for r in reports:
        anchor = f"ticker-{_html.escape(str(r.id))}"
        index_items.append(
            f'<li><a href="#{anchor}">{_html.escape(r.ticker)}</a> '
            f'<span style="color:#888;">(report #{r.id})</span></li>'
        )

    detail_blocks: list[str] = []
    for r in reports:
        anchor = f"ticker-{_html.escape(str(r.id))}"
        inner = render_research_html(r)
        # Crude unwrap of nested <html><body>...</body></html>. Keeps the
        # bundled doc as one valid HTML tree instead of nesting bodies.
        if "<body" in inner.lower():
            try:
                start = inner.lower().index("<body")
                start = inner.index(">", start) + 1
                end = inner.lower().rindex("</body>")
                inner = inner[start:end]
            except ValueError:
                # Malformed envelope — fall through and embed as-is.
                pass
        detail_blocks.append(
            f'<details id="{anchor}" '
            f'style="margin:1rem 0;border:1px solid #ddd;border-radius:6px;'
            f'padding:0.5rem 1rem;">'
            f'<summary style="font-weight:bold;cursor:pointer;'
            f'font-size:1.1rem;">{_html.escape(r.ticker)}</summary>'
            f'<div style="margin-top:0.5rem;">{inner}</div>'
            f'</details>'
        )

    return (
        '<html><body style="font-family:system-ui,-apple-system,sans-serif;'
        'max-width:920px;margin:1rem auto;padding:0 1rem;">'
        f'<h1>Daily SOP Reports — {len(reports)} tickers</h1>'
        '<h2>Index</h2>'
        f'<ul>{"".join(index_items)}</ul>'
        '<hr>'
        f'{"".join(detail_blocks)}'
        '<hr>'
        '<p style="color:#888;font-size:0.85rem;">'
        'Not investment advice -- for your own research.</p>'
        '</body></html>'
    )


def render_bundled_research_text(reports: list) -> str:
    """Plain-text alt-part for the bundled email."""
    if not reports:
        return "No reports produced."
    lines = [f"Daily SOP Reports — {len(reports)} tickers", ""]
    for r in reports:
        lines.append(f"  - {r.ticker} (report #{r.id})")
    lines.append("")
    lines.append("Not investment advice -- for your own research.")
    return "\n".join(lines)
