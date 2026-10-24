"""AnalysisModule contract: subclasses must declare name + supports_personas
and implement run(). Calling the ABC directly must raise."""

from __future__ import annotations

import pytest
from src.research.modules.base import AnalysisModule
from src.research.models import ResearchRequest, ModuleResult
from src.research.shared_data import SharedData


def _fake_request() -> ResearchRequest:
    return ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal="new_entry", use_personas=False,
        scanner_context=None,
    )


def _fake_shared() -> SharedData:
    return SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[],
        news=[], analyst_actions=[], analyst_targets=None,
        earnings_history=[], company_facts={}, sector_etf_prices=[],
        spy_prices=[],
    )


class TestAnalysisModuleABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            AnalysisModule()  # type: ignore[abstract]

    def test_concrete_subclass_runs(self):
        class Dummy(AnalysisModule):
            name = "dummy"
            supports_personas = []

            def run(self, request, persona, shared_data):
                return ModuleResult(
                    module_name=self.name,
                    persona_used=persona,
                    markdown="ok",
                )

        m = Dummy()
        out = m.run(_fake_request(), None, _fake_shared())
        assert out.module_name == "dummy"
        assert out.persona_used is None
        assert out.markdown == "ok"

    def test_concrete_subclass_rejects_unsupported_persona(self):
        class Dummy(AnalysisModule):
            name = "dummy"
            supports_personas = ["buffett"]

            def run(self, request, persona, shared_data):
                return ModuleResult(module_name=self.name,
                                    persona_used=persona, markdown="ok")

        m = Dummy()
        # Validation helper provided by the base class — modules call it
        # in their own run() to coerce bad persona to None.
        assert m._coerce_persona("buffett") == "buffett"
        assert m._coerce_persona("wood") is None  # not in supports_personas
        assert m._coerce_persona(None) is None
