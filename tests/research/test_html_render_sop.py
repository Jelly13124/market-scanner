"""HTML render: AnalyzeReport -> single self-contained HTML string."""

from src.research.html_render import render_sop
from src.research.models import (
    AnalyzeRequest, AnalyzeReport, BacktestVerdict, SectionPayload,
    SECTION_ORDER,
)


def _section(name, markdown="body", skipped=False, skip_reason=None, structured=None):
    return SectionPayload(
        name=name, markdown=markdown, structured=structured,
        skipped=skipped, persona_used=None, skip_reason=skip_reason,
    )


def _report(score=42, sections_override=None):
    req = AnalyzeRequest(
        ticker="NVDA", objective="medium_term",
        position_budget_usd=10000, already_holds=False, cost_basis_usd=None,
        risk_tolerance="balanced", use_personas=True,
    )
    sections = {n: _section(n, markdown=f"## {n}\n\nbody for {n}.")
                for n in SECTION_ORDER}
    # Conviction has a structured total_score
    sections["conviction"] = _section(
        "conviction", markdown="## Conviction\n\nbody.",
        structured={"total_score": score, "categories": [], "weights": [],
                    "risk_profile": "balanced"},
    )
    if sections_override:
        sections.update(sections_override)
    return AnalyzeReport(
        request=req, sections=sections,
        persona_assignments={"fundamentals": "buffett"},
        backtest=BacktestVerdict(
            signal="rsi_oversold", window_start="2020-01-01",
            window_end="2026-05-22", n_signals=10, win_rate_20d=0.6,
            avg_return_20d=0.02, t_stat=2.1, significant=True,
            verdict="significant edge",
        ),
        rendered_html=None,
    )


class TestRenderSop:
    def test_returns_complete_html_doc(self):
        html = render_sop(_report())
        # DOCTYPE somewhere near top (template may have a leading comment block)
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html

    def test_ticker_in_html(self):
        html = render_sop(_report())
        assert "NVDA" in html

    def test_score_from_conviction_appears(self):
        html = render_sop(_report(score=42))
        assert "42" in html

    def test_skipped_section_renders_na(self):
        """A skipped section's body must render 'n/a' / 'unavailable', NOT
        silently omit the section. The <h2> heading itself is in the
        template — we just inject the body."""
        sections = {"valuation": _section(
            "valuation", markdown="## Valuation Analysis\n\n_n/a -- user excluded_",
            skipped=True, skip_reason="user excluded",
        )}
        html = render_sop(_report(sections_override=sections))
        # The skipped section's body content should appear in the html
        assert "user excluded" in html.lower() or "n/a" in html.lower()

    def test_section_body_injected_under_correct_heading(self):
        """data_health section markdown must end up under '<h2>Data Health</h2>'
        in the rendered output."""
        sections = {"data_health": _section(
            "data_health",
            markdown="## Data Health\n\nUNIQUEDH_MARKER body.",
        )}
        html = render_sop(_report(sections_override=sections))
        # The marker text should appear AFTER the Data Health heading
        dh_pos = html.find("Data Health")
        marker_pos = html.find("UNIQUEDH_MARKER")
        assert dh_pos > 0
        assert marker_pos > dh_pos


    def test_objective_in_html(self):
        html = render_sop(_report())
        # the objective scalar gets rendered somewhere (probably in the timestamp block)
        assert "medium_term" in html
