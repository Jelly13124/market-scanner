from unittest.mock import patch
from src.research.models import AnalyzeRequest
from src.research.sections.base import SectionContext
from src.research.shared_data import SharedData


def _ctx():
    req = AnalyzeRequest(
        ticker="NVDA", objective="medium_term",
        position_budget_usd=10000, already_holds=False, cost_basis_usd=None,
        risk_tolerance="balanced", use_personas=False,
    )
    shared = SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[], news=[],
        analyst_actions=[], analyst_targets=None, earnings_history=[],
        company_facts={}, sector_etf_prices=[], spy_prices=[],
    )
    return SectionContext(request=req, shared=shared, persona=None, prior={})


@patch("src.research.sections.evidence_ledger.call_research_llm")
def test_emits_table_and_structured(mock_llm):
    from src.research.sections.evidence_ledger import (
        EvidenceLedgerSection, _LedgerOut, _Evidence)
    items = [
        _Evidence(claim=f"c{i}", evidence=f"e{i}", source="src",
                  date="2026-05-22", direction="bullish", confidence="high")
        for i in range(10)
    ]
    mock_llm.return_value = _LedgerOut(items=items)
    out = EvidenceLedgerSection().run(_ctx())
    assert out.name == "evidence_ledger"
    assert "| Claim |" in out.markdown
    # 10 data rows + header + separator = 12 lines minimum
    assert out.markdown.count("\n|") >= 11
    assert isinstance(out.structured, list)
    assert len(out.structured) == 10


@patch("src.research.sections.evidence_ledger.call_research_llm")
def test_skipped_on_exception(mock_llm):
    from src.research.sections.evidence_ledger import EvidenceLedgerSection
    mock_llm.side_effect = Exception("boom")
    out = EvidenceLedgerSection().run(_ctx())
    assert out.skipped is True
    assert "boom" in (out.skip_reason or "")


def test_registered():
    from src.research.sections import SECTION_REGISTRY
    from src.research.sections.evidence_ledger import EvidenceLedgerSection
    assert "evidence_ledger" in SECTION_REGISTRY
    assert isinstance(SECTION_REGISTRY["evidence_ledger"], EvidenceLedgerSection)
