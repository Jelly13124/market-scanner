"""Offline tests for the Ownership Structure SOP section.

No network, no LLM:
  * ``call_research_llm`` is patched on the shared ``_llm_runner``.
  * ``fetch_ownership`` is patched on the SECTION module so yfinance is never
    touched; the insider net is computed from synthetic ``shared.insider_trades``.

Asserts the grounded block surfaces insider %, institution %, top holders, and
the insider-transaction net. Missing ownership data must render a "data
unavailable" note WITHOUT raising (the ticker is still reported).
"""

from __future__ import annotations

from unittest.mock import patch

from src.research.models import AnalyzeRequest
from src.research.sections.base import SectionContext
from src.research.shared_data import SharedData


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


class _Trade:
    def __init__(self, shares, value=None):
        self.transaction_shares = shares
        self.transaction_value = value


def _ownership_dict():
    return {
        "insider_pct": 0.0007,
        "institution_pct": 0.62,
        "institution_count": 4321,
        "top_holders": [
            {"name": "Vanguard Group Inc", "pct": 0.0834},
            {"name": "Blackrock Inc.", "pct": 0.0651},
            {"name": "State Street Corp", "pct": 0.0398},
        ],
        "shares_outstanding": 15_000_000_000,
    }


def _ctx(insider_trades=None):
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
        insider_trades=insider_trades if insider_trades is not None else [],
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
def test_grounded_block_has_ownership_and_insider_net(mock_llm):
    from src.research.sections.ownership_structure import (
        OwnershipStructureSection,
        _Narrative,
    )

    captured = {}

    def _capture(prompt, model, **kw):
        captured["prompt"] = prompt
        return _Narrative(narrative="ok")

    mock_llm.side_effect = _capture

    # net = +5000 - 1000 = +4000 shares => net buying
    trades = [_Trade(5000.0, 500_000.0), _Trade(-1000.0, -100_000.0)]
    with patch(
        "src.research.sections.ownership_structure.fetch_ownership",
        return_value=_ownership_dict(),
    ):
        out = OwnershipStructureSection().run(_ctx(insider_trades=trades))

    assert out.name == "ownership_structure"
    assert out.skipped is False
    p = captured["prompt"]
    # insider % (0.0007 -> 0.07%) and institution % (0.62 -> 62.00%)
    assert "0.07%" in p
    assert "62.00%" in p
    # institution count + top holders
    assert "4,321" in p or "4321" in p
    assert "Vanguard Group Inc" in p
    assert "8.34%" in p  # top holder pct
    # insider net (signed share count) + direction
    assert "4,000" in p or "4000" in p
    assert "buying" in p.lower()


@patch("src.research.sections._llm_runner.call_research_llm")
def test_insider_net_selling_direction(mock_llm):
    from src.research.sections.ownership_structure import (
        OwnershipStructureSection,
        _Narrative,
    )

    captured = {}

    def _capture(prompt, model, **kw):
        captured["prompt"] = prompt
        return _Narrative(narrative="ok")

    mock_llm.side_effect = _capture

    trades = [_Trade(1000.0), _Trade(-9000.0)]  # net -8000 => selling
    with patch(
        "src.research.sections.ownership_structure.fetch_ownership",
        return_value=_ownership_dict(),
    ):
        OwnershipStructureSection().run(_ctx(insider_trades=trades))

    p = captured["prompt"]
    assert "selling" in p.lower()


@patch("src.research.sections._llm_runner.call_research_llm")
def test_no_insider_trades_renders_na_net(mock_llm):
    from src.research.sections.ownership_structure import (
        OwnershipStructureSection,
        _Narrative,
    )

    captured = {}

    def _capture(prompt, model, **kw):
        captured["prompt"] = prompt
        return _Narrative(narrative="ok")

    mock_llm.side_effect = _capture

    with patch(
        "src.research.sections.ownership_structure.fetch_ownership",
        return_value=_ownership_dict(),
    ):
        OwnershipStructureSection().run(_ctx(insider_trades=[]))

    p = captured["prompt"]
    # ownership present, but insider net has no data
    assert "62.00%" in p
    assert "n/a" in p


# --------------------------------------------------------------------------- #
# Never-raise on missing data
# --------------------------------------------------------------------------- #


@patch("src.research.sections._llm_runner.call_research_llm")
def test_all_none_ownership_renders_unavailable_note(mock_llm):
    from src.research.sections.ownership_structure import (
        OwnershipStructureSection,
        _Narrative,
    )

    captured = {}

    def _capture(prompt, model, **kw):
        captured["prompt"] = prompt
        return _Narrative(narrative="ok")

    mock_llm.side_effect = _capture

    none_dict = {
        "insider_pct": None,
        "institution_pct": None,
        "institution_count": None,
        "top_holders": None,
        "shares_outstanding": None,
    }
    with patch(
        "src.research.sections.ownership_structure.fetch_ownership",
        return_value=none_dict,
    ):
        out = OwnershipStructureSection().run(_ctx(insider_trades=[]))

    assert out.skipped is False  # honest note, not a skip
    assert "unavailable" in captured["prompt"].lower()


@patch("src.research.sections._llm_runner.call_research_llm")
def test_fetch_ownership_raises_is_swallowed(mock_llm):
    from src.research.sections.ownership_structure import (
        OwnershipStructureSection,
        _Narrative,
    )

    mock_llm.return_value = _Narrative(narrative="ok")

    def _boom(*a, **k):
        raise RuntimeError("yfinance down")

    with patch(
        "src.research.sections.ownership_structure.fetch_ownership",
        side_effect=_boom,
    ):
        out = OwnershipStructureSection().run(_ctx(insider_trades=[]))  # must NOT raise

    assert out.name == "ownership_structure"
    assert out.skipped is False


# --------------------------------------------------------------------------- #
# Wiring
# --------------------------------------------------------------------------- #


def test_registered_in_section_registry():
    from src.research.sections import SECTION_REGISTRY
    from src.research.sections.ownership_structure import OwnershipStructureSection

    assert "ownership_structure" in SECTION_REGISTRY
    assert isinstance(SECTION_REGISTRY["ownership_structure"], OwnershipStructureSection)
