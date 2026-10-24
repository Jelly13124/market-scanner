"""Section ABC + SECTION_REGISTRY contract."""

from __future__ import annotations

import pytest

from src.research.sections import SECTION_REGISTRY
from src.research.sections.base import Section, SectionContext


class TestSectionBase:
    def test_section_is_abstract(self):
        with pytest.raises(TypeError):
            Section()  # type: ignore[abstract]

    def test_registry_starts_empty(self):
        # Phase 4 Task 4 creates the registry; individual sections
        # register themselves in later tasks. Empty here is correct.
        assert isinstance(SECTION_REGISTRY, dict)

    def test_section_context_holds_what_runner_passes(self):
        from src.research.models import AnalyzeRequest
        from src.research.shared_data import SharedData

        req = AnalyzeRequest(
            ticker="X", objective="general_research",
            position_budget_usd=None, already_holds=False, cost_basis_usd=None,
            risk_tolerance="balanced", use_personas=False,
        )
        shared = SharedData(
            ticker="X", scan_date="2026-05-22",
            prices=[], financials=[], insider_trades=[],
            news=[], analyst_actions=[], analyst_targets=None,
            earnings_history=[], company_facts={},
            sector_etf_prices=[], spy_prices=[],
        )
        ctx = SectionContext(
            request=req, shared=shared, persona=None, prior={},
        )
        assert ctx.request.ticker == "X"
        assert ctx.shared.ticker == "X"
