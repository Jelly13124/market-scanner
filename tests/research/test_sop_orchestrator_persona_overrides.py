"""Tests for Phase 5D persona_overrides in the SOP orchestrator."""

from __future__ import annotations

from unittest.mock import patch

from src.research.models import (
    AnalyzeRequest,
    BacktestVerdict,
    SECTION_ORDER,
    SectionPayload,
)
from src.research.sop_orchestrator import run_sop


def _req(
    *,
    use_personas: bool = False,
    persona_overrides: dict[str, str] | None = None,
):
    return AnalyzeRequest(
        ticker="NVDA",
        objective="medium_term",
        position_budget_usd=10000,
        already_holds=False,
        cost_basis_usd=None,
        risk_tolerance="balanced",
        use_personas=use_personas,
        included_sections=set(SECTION_ORDER),
        persona_overrides=persona_overrides,
    )


def _stub_shared():
    from src.research.shared_data import SharedData
    return SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[], news=[],
        analyst_actions=[], analyst_targets=None, earnings_history=[],
        company_facts={}, sector_etf_prices=[], spy_prices=[],
    )


def _stub_backtest():
    return BacktestVerdict(
        signal="rsi_oversold", window_start="x", window_end="x",
        n_signals=0, win_rate_20d=None, avg_return_20d=None,
        t_stat=None, significant=False, verdict="x",
    )


class _CapturingStub:
    """Test double — remembers what persona it was handed via SectionContext."""

    def __init__(self, name: str):
        self.name = name
        self.supports_personas: list[str] = []
        self.received_persona: str | None = None

    def run(self, ctx):
        self.received_persona = ctx.persona
        return SectionPayload(
            name=self.name, markdown=f"## {self.name}",
            structured=None, skipped=False, persona_used=self.received_persona,
        )


def _stub_registry() -> dict[str, _CapturingStub]:
    return {name: _CapturingStub(name) for name in SECTION_ORDER}


@patch("src.research.sop_orchestrator.fetch_shared_data")
@patch("src.research.sop_orchestrator.SECTION_REGISTRY", new_callable=dict)
@patch("src.research.sop_orchestrator.run_signal_backtest")
@patch("src.research.sop_orchestrator.route_personas")
def test_override_takes_precedence_over_router(
    mock_router, mock_bt, mock_registry, mock_fetch,
):
    """Section listed in persona_overrides wins over the router's assignment."""
    mock_fetch.return_value = _stub_shared()
    mock_bt.return_value = _stub_backtest()
    # Router uses canonical SECTION_ORDER names so the orchestrator's
    # direct dict lookup resolves them.
    mock_router.return_value = {
        "company_fundamentals": "buffett",
        "valuation": "graham",
        "risk_position": None,
        "debate": [],
        "_rationale": "x",
    }
    stubs = _stub_registry()
    for n, s in stubs.items():
        mock_registry[n] = s

    # User pins valuation to munger — that should override router's graham
    run_sop(_req(use_personas=True, persona_overrides={"valuation": "munger"}))
    assert stubs["valuation"].received_persona == "munger"
    # company_fundamentals NOT in override → router's buffett still wins
    assert stubs["company_fundamentals"].received_persona == "buffett"


@patch("src.research.sop_orchestrator.fetch_shared_data")
@patch("src.research.sop_orchestrator.SECTION_REGISTRY", new_callable=dict)
@patch("src.research.sop_orchestrator.run_signal_backtest")
@patch("src.research.sop_orchestrator.route_personas")
def test_partial_override_only_affects_listed_sections(
    mock_router, mock_bt, mock_registry, mock_fetch,
):
    """Sections not in overrides fall through to router's assignment."""
    mock_fetch.return_value = _stub_shared()
    mock_bt.return_value = _stub_backtest()
    mock_router.return_value = {
        "company_fundamentals": "fisher",
        "valuation": "graham",
        "risk_position": "burry",
        "debate": [],
        "_rationale": "x",
    }
    stubs = _stub_registry()
    for n, s in stubs.items():
        mock_registry[n] = s

    # Only pin risk_position
    run_sop(_req(
        use_personas=True,
        persona_overrides={"risk_position": "druckenmiller"},
    ))
    assert stubs["risk_position"].received_persona == "druckenmiller"
    # Other persona-aware sections defer to router
    assert stubs["company_fundamentals"].received_persona == "fisher"
    assert stubs["valuation"].received_persona == "graham"


@patch("src.research.sop_orchestrator.fetch_shared_data")
@patch("src.research.sop_orchestrator.SECTION_REGISTRY", new_callable=dict)
@patch("src.research.sop_orchestrator.run_signal_backtest")
@patch("src.research.sop_orchestrator.route_personas")
def test_none_overrides_is_phase4_regression_guard(
    mock_router, mock_bt, mock_registry, mock_fetch,
):
    """persona_overrides=None must behave exactly like Phase 4.

    With use_personas=False (no router), every persona handed to sections
    must be None.
    """
    mock_fetch.return_value = _stub_shared()
    mock_bt.return_value = _stub_backtest()
    stubs = _stub_registry()
    for n, s in stubs.items():
        mock_registry[n] = s

    run_sop(_req(use_personas=False, persona_overrides=None))
    mock_router.assert_not_called()
    for stub in stubs.values():
        assert stub.received_persona is None
