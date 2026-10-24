"""Offline tests for the Capital Structure SOP section.

No network, no LLM:
  * ``call_research_llm`` is patched on the shared ``_llm_runner`` so the LLM is
    never called (DeepSeek balance is depleted — tests must stub it).
  * ``search_line_items`` is patched on the SECTION module so yfinance is never
    touched; we inject synthetic line items with known numbers + ``report_period``.

The grounded block is captured out of the prompt handed to the LLM and asserted
to carry the computed ratios. Missing line items must render a "data
unavailable" note WITHOUT raising (the ticker is still reported).
"""

from __future__ import annotations

from unittest.mock import patch

from src.research.models import AnalyzeRequest
from src.research.sections.base import SectionContext
from src.research.shared_data import SharedData


# --------------------------------------------------------------------------- #
# Synthetic line items
# --------------------------------------------------------------------------- #


class _LI:
    """A duck-typed line-item record (search_line_items returns LineItem, which
    exposes the requested fields as dynamic attrs + a report_period)."""

    def __init__(self, report_period, **fields):
        self.report_period = report_period
        for k, v in fields.items():
            setattr(self, k, v)


def _items_two_years():
    # Newest first (search_line_items returns newest-first). report_period well
    # outside the 60d lag from the 2026-05-22 scan_date so it is "knowable".
    latest = _LI(
        "2025-09-30",
        total_debt=120_000.0,
        shareholders_equity=300_000.0,
        total_liabilities=250_000.0,
        total_assets=500_000.0,
        cash_and_equivalents=40_000.0,
        operating_income=90_000.0,
        interest_expense=10_000.0,
        outstanding_shares=1_000.0,
    )
    prior = _LI(
        "2024-09-30",
        total_debt=110_000.0,
        shareholders_equity=260_000.0,
        total_liabilities=240_000.0,
        total_assets=470_000.0,
        cash_and_equivalents=35_000.0,
        operating_income=80_000.0,
        interest_expense=9_000.0,
        outstanding_shares=900.0,  # fewer shares last year => dilution this year
    )
    return [latest, prior]


def _ctx():
    req = AnalyzeRequest(
        ticker="NVDA",
        objective="medium_term",
        position_budget_usd=10000,
        already_holds=False,
        cost_basis_usd=None,
        risk_tolerance="balanced",
        use_personas=False,
    )
    shared = SharedData(
        ticker="NVDA",
        scan_date="2026-05-22",
        prices=[],
        financials=[],
        insider_trades=[],
        news=[],
        analyst_actions=[],
        analyst_targets=None,
        earnings_history=[],
        company_facts={"sector": "Tech"},
        sector_etf_prices=[],
        spy_prices=[],
    )
    return SectionContext(request=req, shared=shared, persona=None, prior={})


# --------------------------------------------------------------------------- #
# Grounded block content
# --------------------------------------------------------------------------- #


@patch("src.research.sections._llm_runner.call_research_llm")
def test_grounded_block_has_computed_ratios(mock_llm):
    from src.research.sections.capital_structure import (
        CapitalStructureSection,
        _Narrative,
    )

    captured = {}

    def _capture(prompt, model, **kw):
        captured["prompt"] = prompt
        return _Narrative(narrative="ok")

    mock_llm.side_effect = _capture

    with patch(
        "src.research.sections.capital_structure.search_line_items",
        return_value=_items_two_years(),
    ):
        out = CapitalStructureSection().run(_ctx())

    assert out.name == "capital_structure"
    assert out.skipped is False
    p = captured["prompt"]
    # debt/equity = 120000/300000 = 0.40
    assert "0.40" in p
    # net debt = 120000 - 40000 = 80000
    assert "80,000" in p or "80000" in p
    # leverage = 250000/500000 = 0.50
    assert "0.50" in p
    # interest coverage = 90000/10000 = 9.0
    assert "9.0" in p or "9.00" in p
    # shares outstanding
    assert "1,000" in p or "1000" in p
    # YoY dilution = 1000/900 - 1 = +11.1%
    assert "11.1%" in p


@patch("src.research.sections._llm_runner.call_research_llm")
def test_zero_denominator_renders_na(mock_llm):
    from src.research.sections.capital_structure import (
        CapitalStructureSection,
        _Narrative,
    )

    captured = {}

    def _capture(prompt, model, **kw):
        captured["prompt"] = prompt
        return _Narrative(narrative="ok")

    mock_llm.side_effect = _capture

    # equity = 0 (D/E n/a), total_assets = 0 (leverage n/a), interest_expense=0
    items = [
        _LI(
            "2025-09-30",
            total_debt=120_000.0,
            shareholders_equity=0.0,
            total_liabilities=250_000.0,
            total_assets=0.0,
            cash_and_equivalents=40_000.0,
            operating_income=90_000.0,
            interest_expense=0.0,
            outstanding_shares=1_000.0,
        )
    ]
    with patch(
        "src.research.sections.capital_structure.search_line_items",
        return_value=items,
    ):
        out = CapitalStructureSection().run(_ctx())

    assert out.skipped is False
    p = captured["prompt"]
    assert "n/a" in p  # at least one ratio guarded


@patch("src.research.sections._llm_runner.call_research_llm")
def test_omits_interest_coverage_without_operating_income(mock_llm):
    from src.research.sections.capital_structure import (
        CapitalStructureSection,
        _Narrative,
    )

    captured = {}

    def _capture(prompt, model, **kw):
        captured["prompt"] = prompt
        return _Narrative(narrative="ok")

    mock_llm.side_effect = _capture

    items = [
        _LI(
            "2025-09-30",
            total_debt=120_000.0,
            shareholders_equity=300_000.0,
            total_liabilities=250_000.0,
            total_assets=500_000.0,
            cash_and_equivalents=40_000.0,
            operating_income=None,  # no operating income => omit coverage
            interest_expense=10_000.0,
            outstanding_shares=1_000.0,
        )
    ]
    with patch(
        "src.research.sections.capital_structure.search_line_items",
        return_value=items,
    ):
        out = CapitalStructureSection().run(_ctx())

    p = captured["prompt"]
    assert "Interest coverage" not in p
    # but the other ratios are still present
    assert "Debt / equity" in p


# --------------------------------------------------------------------------- #
# Never-raise on missing data
# --------------------------------------------------------------------------- #


@patch("src.research.sections._llm_runner.call_research_llm")
def test_no_line_items_renders_unavailable_note(mock_llm):
    from src.research.sections.capital_structure import (
        CapitalStructureSection,
        _Narrative,
    )

    captured = {}

    def _capture(prompt, model, **kw):
        captured["prompt"] = prompt
        return _Narrative(narrative="ok")

    mock_llm.side_effect = _capture

    with patch(
        "src.research.sections.capital_structure.search_line_items",
        return_value=[],
    ):
        out = CapitalStructureSection().run(_ctx())

    assert out.skipped is False  # honest note, not a skip
    assert "unavailable" in captured["prompt"].lower()


@patch("src.research.sections._llm_runner.call_research_llm")
def test_search_line_items_raises_is_swallowed(mock_llm):
    from src.research.sections.capital_structure import (
        CapitalStructureSection,
        _Narrative,
    )

    mock_llm.return_value = _Narrative(narrative="ok")

    def _boom(*a, **k):
        raise RuntimeError("yfinance down")

    with patch(
        "src.research.sections.capital_structure.search_line_items",
        side_effect=_boom,
    ):
        out = CapitalStructureSection().run(_ctx())  # must NOT raise

    assert out.name == "capital_structure"
    assert out.skipped is False


# --------------------------------------------------------------------------- #
# Wiring
# --------------------------------------------------------------------------- #


def test_registered_in_section_registry():
    from src.research.sections import SECTION_REGISTRY
    from src.research.sections.capital_structure import CapitalStructureSection

    assert "capital_structure" in SECTION_REGISTRY
    assert isinstance(SECTION_REGISTRY["capital_structure"], CapitalStructureSection)
