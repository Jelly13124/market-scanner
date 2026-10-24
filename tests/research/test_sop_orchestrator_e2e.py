"""E2E integration test for run_sop using the REAL SECTION_REGISTRY.

Catches bugs like the one fixed in 708b1bd where section modules
were not imported in sections/__init__.py — so SECTION_REGISTRY was
empty and every section emitted 'section not yet implemented'.

Mocks only fetch_shared_data, call_research_llm, route_personas to
keep the test offline + deterministic. Section runners themselves
run for real.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import BaseModel

from src.research.models import AnalyzeRequest, SECTION_ORDER


def _fake_shared():
    """Realistic-ish shared data so deterministic sections find content."""
    from src.research.shared_data import SharedData
    return SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[{"open": 100.0 + i*0.1, "close": 100.0 + i*0.1,
                 "high": 100.0 + i*0.1, "low": 100.0 + i*0.1,
                 "volume": 1e6, "time": str(i)} for i in range(300)],
        financials=[],
        insider_trades=[{"trade": "x"}],
        news=[{"title": "x"}],
        analyst_actions=[{"action": "x"}],
        analyst_targets={"target_mean": 200},
        earnings_history=[],
        company_facts={"sector": "Technology"},
        sector_etf_prices=[100.0 + i*0.1 for i in range(50)],
        spy_prices=[400.0 + i*0.1 for i in range(50)],
    )


def _req(use_personas=False, included=None):
    return AnalyzeRequest(
        ticker="NVDA", objective="medium_term",
        position_budget_usd=10000, already_holds=False, cost_basis_usd=None,
        risk_tolerance="balanced", use_personas=use_personas,
        included_sections=included if included is not None else set(SECTION_ORDER),
    )


def _fake_llm_response(model_cls):
    """Return a populated instance of any pydantic _Narrative or
    section output model the SOP code throws at us. Handles every
    output model shape we have."""
    # Most sections use a model with a `narrative` field
    fields = model_cls.model_fields if hasattr(model_cls, "model_fields") else {}

    # If has 'narrative' field, that's the simple case
    if "narrative" in fields:
        return model_cls(narrative="LLM narrative body, ~200 words for the test.")

    # EvidenceLedger: model has 'items' list[_Evidence]
    if "items" in fields:
        from src.research.sections.evidence_ledger import _Evidence
        items = [_Evidence(
            claim=f"claim {i}", evidence=f"evidence {i}", source="test",
            date="2026-05-22", direction="bullish", confidence="high",
        ) for i in range(10)]
        return model_cls(items=items)

    # Scenarios: bear/base/bull
    if "bear" in fields and "base" in fields and "bull" in fields:
        from src.research.sections.scenarios import _Scenario
        s = _Scenario(target_range="$100-110", time_horizon="3m",
                      key_assumptions="x", confidence="medium",
                      invalidation="x")
        return model_cls(bear=s, base=s, bull=s)

    # Conviction: 6 categories
    if "categories" in fields:
        from src.research.sections.conviction import _CategoryScore, _CATEGORIES
        cats = [_CategoryScore(name=c, score=70, rationale="x")
                for c in _CATEGORIES]
        return model_cls(categories=cats)

    # ExecutiveSummary: many fields
    if "overall_view" in fields:
        return model_cls(
            overall_view="bullish", main_bullish="ai growth",
            main_bearish="competition", target_range="$100/120/140",
            strategy_type="swing", confidence_qualitative="medium",
            key_invalidation="earnings miss",
        )

    # Router output (if it slips through — but we mock route_personas separately)
    raise ValueError(f"unhandled model class: {model_cls}")


class TestSopOrchestratorE2E:
    @patch("src.research.sop_orchestrator.fetch_shared_data")
    @patch("src.research.sop_orchestrator.route_personas")
    def test_real_registry_runs_all_sections(self, mock_router, mock_fetch):
        """The real SECTION_REGISTRY must contain all 16 sections.
        Each section's run() must produce a non-'not yet implemented'
        payload. Catches the import-side-effect bug fixed in 708b1bd."""
        from src.research.sections import SECTION_REGISTRY
        from src.research.sop_orchestrator import run_sop

        # Sanity: all 16 SOP sections should have a runner BEFORE we run
        for name in SECTION_ORDER:
            assert name in SECTION_REGISTRY, f"missing runner for {name!r}"

        mock_fetch.return_value = _fake_shared()
        mock_router.return_value = None

        # Patch call_research_llm to satisfy any section that calls LLM
        with patch("src.research.sections._llm_runner.call_research_llm") as mock_llm_a, \
             patch("src.research.sections.evidence_ledger.call_research_llm") as mock_llm_b, \
             patch("src.research.sections.scenarios.call_research_llm") as mock_llm_c, \
             patch("src.research.sections.conviction.call_research_llm") as mock_llm_d, \
             patch("src.research.sections.executive_summary.call_research_llm") as mock_llm_e:
            for m in (mock_llm_a, mock_llm_b, mock_llm_c, mock_llm_d, mock_llm_e):
                m.side_effect = lambda prompt, model_cls, **kw: _fake_llm_response(model_cls)
            report = run_sop(_req())

        sections = report["sections"]

        # The bug we caught: 'section not yet implemented' should NEVER
        # appear when SECTION_REGISTRY is properly populated.
        for name in SECTION_ORDER:
            payload = sections[name]
            assert "not yet implemented" not in payload.markdown, (
                f"section {name!r} emitted 'not yet implemented' — "
                f"likely import-side-effect bug. skip_reason={payload.skip_reason}"
            )

        # Deterministic sections (data_health, missing_data) must produce
        # real markdown output without an LLM call.
        assert "Data Health" in sections["data_health"].markdown
        assert sections["data_health"].skipped is False

    def test_section_registry_has_all_16_at_import_time(self):
        """A bare-minimum check that's cheap and catches the same bug
        without running any orchestrator code at all."""
        from src.research.sections import SECTION_REGISTRY
        missing = [n for n in SECTION_ORDER if n not in SECTION_REGISTRY]
        assert missing == [], (
            f"SECTION_REGISTRY missing entries for: {missing}. "
            "Probably forgot to import the module in src/research/sections/__init__.py"
        )

    @patch("src.research.sop_orchestrator.fetch_shared_data")
    def test_excluded_sections_still_render_as_user_excluded(self, mock_fetch):
        """Smoke that user-excluded sections render the right reason
        (NOT 'not yet implemented')."""
        from src.research.sop_orchestrator import run_sop
        mock_fetch.return_value = _fake_shared()

        with patch("src.research.sections._llm_runner.call_research_llm") as m_a, \
             patch("src.research.sections.evidence_ledger.call_research_llm") as m_b, \
             patch("src.research.sections.scenarios.call_research_llm") as m_c, \
             patch("src.research.sections.conviction.call_research_llm") as m_d, \
             patch("src.research.sections.executive_summary.call_research_llm") as m_e:
            for m in (m_a, m_b, m_c, m_d, m_e):
                m.side_effect = lambda prompt, model_cls, **kw: _fake_llm_response(model_cls)
            report = run_sop(_req(included={"data_health", "executive_summary"}))

        # Excluded sections get the user-excluded message, not the
        # implementation-missing one
        for name in SECTION_ORDER:
            if name in {"data_health", "executive_summary"}:
                continue
            assert "user excluded" in (report["sections"][name].skip_reason or "")
            assert "not yet implemented" not in report["sections"][name].markdown
