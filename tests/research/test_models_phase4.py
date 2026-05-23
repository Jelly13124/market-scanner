from src.research.models import (
    AnalyzeRequest, AnalyzeReport, SectionPayload, BacktestVerdict,
    SECTION_ORDER,
)


def test_analyze_request_has_required_fields():
    req = AnalyzeRequest(
        ticker="NVDA",
        objective="medium_term",
        position_budget_usd=10000,
        already_holds=False, cost_basis_usd=None,
        risk_tolerance="balanced",
        use_personas=True,
        included_sections=set(SECTION_ORDER),
    )
    assert req.ticker == "NVDA"
    assert "executive_summary" in req.included_sections


def test_section_order_has_16_canonical_sections():
    expected = {
        "data_health", "executive_summary", "evidence_ledger",
        "macro", "sector", "company_fundamentals", "financial_statements",
        "valuation", "technical", "risk_position", "scenarios",
        "conviction", "event_risk", "debate", "final_strategy",
        "missing_data",
    }
    assert set(SECTION_ORDER) == expected
    # order matters - data_health first, missing_data last
    assert SECTION_ORDER[0] == "data_health"
    assert SECTION_ORDER[-1] == "missing_data"


def test_section_payload_shape():
    p = SectionPayload(
        name="macro",
        markdown="# Macro\n\nUp regime.",
        structured=None,
        skipped=False,
        persona_used=None,
    )
    assert p.name == "macro"
    assert p.skipped is False


def test_analyze_report_assembles_sections():
    sections = {
        "data_health": SectionPayload(name="data_health", markdown="ok", structured=None, skipped=False, persona_used=None),
    }
    rep = AnalyzeReport(
        request=AnalyzeRequest(
            ticker="X", objective="general_research",
            position_budget_usd=None, already_holds=False, cost_basis_usd=None,
            risk_tolerance="balanced", use_personas=False,
            included_sections={"data_health"},
        ),
        sections=sections,
        persona_assignments=None,
        backtest=None,
        rendered_html=None,
    )
    assert rep["sections"]["data_health"].name == "data_health"


def test_backtest_verdict_shape():
    v = BacktestVerdict(
        signal="rsi_oversold",
        window_start="2020-01-01", window_end="2026-05-22",
        n_signals=42, win_rate_20d=0.55, avg_return_20d=0.018,
        t_stat=1.7, significant=False,
        verdict="weak edge; not significant at p<0.05",
    )
    assert v.signal == "rsi_oversold"
