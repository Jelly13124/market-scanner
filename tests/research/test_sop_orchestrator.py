"""Tests for SOP orchestrator (Phase 4 Task 15)."""

from __future__ import annotations

from unittest.mock import patch

from src.research.models import (
    AnalyzeRequest,
    BacktestVerdict,
    SECTION_ORDER,
    SectionPayload,
)
from src.research.sop_orchestrator import run_sop


def _req(use_personas=False, included=None):
    return AnalyzeRequest(
        ticker="NVDA",
        objective="medium_term",
        position_budget_usd=10000,
        already_holds=False,
        cost_basis_usd=None,
        risk_tolerance="balanced",
        use_personas=use_personas,
        included_sections=included if included is not None else set(SECTION_ORDER),
    )


@patch("src.research.sop_orchestrator.fetch_shared_data")
@patch("src.research.sop_orchestrator.SECTION_REGISTRY", new_callable=dict)
@patch("src.research.sop_orchestrator.run_signal_backtest")
def test_runs_all_sections_in_order(mock_bt, mock_registry, mock_fetch):
    from src.research.shared_data import SharedData
    mock_fetch.return_value = SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[], news=[],
        analyst_actions=[], analyst_targets=None, earnings_history=[],
        company_facts={}, sector_etf_prices=[], spy_prices=[],
    )
    mock_bt.return_value = BacktestVerdict(
        signal="rsi_oversold", window_start="2020-01-01",
        window_end="2026-05-22", n_signals=10, win_rate_20d=0.6,
        avg_return_20d=0.02, t_stat=2.1, significant=True,
        verdict="significant at p<0.05",
    )

    call_log = []

    class _StubSection:
        def __init__(self, name):
            self.name = name
            self.supports_personas = []

        def run(self, ctx):
            call_log.append(self.name)
            return SectionPayload(
                name=self.name, markdown=f"## {self.name}\n\nbody.",
                structured=None, skipped=False, persona_used=None,
            )

    for n in SECTION_ORDER:
        mock_registry[n] = _StubSection(n)

    report = run_sop(_req())
    # Every section ran, in order
    assert call_log == SECTION_ORDER
    assert "data_health" in report["sections"]
    assert report["backtest"].n_signals == 10


@patch("src.research.sop_orchestrator.fetch_shared_data")
@patch("src.research.sop_orchestrator.SECTION_REGISTRY", new_callable=dict)
@patch("src.research.sop_orchestrator.run_signal_backtest")
def test_skips_excluded_sections(mock_bt, mock_registry, mock_fetch):
    from src.research.shared_data import SharedData
    mock_fetch.return_value = SharedData(
        ticker="X", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[], news=[],
        analyst_actions=[], analyst_targets=None, earnings_history=[],
        company_facts={}, sector_etf_prices=[], spy_prices=[],
    )
    mock_bt.return_value = BacktestVerdict(
        signal="rsi_oversold", window_start="x", window_end="x",
        n_signals=0, win_rate_20d=None, avg_return_20d=None,
        t_stat=None, significant=False, verdict="x",
    )

    class _Stub:
        def __init__(self, name):
            self.name = name
            self.supports_personas = []

        def run(self, ctx):
            return SectionPayload(
                name=self.name, markdown=f"## {self.name}",
                structured=None, skipped=False, persona_used=None,
            )

    for n in SECTION_ORDER:
        mock_registry[n] = _Stub(n)

    report = run_sop(_req(included={"data_health", "executive_summary"}))
    assert report["sections"]["macro"].skipped is True
    assert "user excluded" in (report["sections"]["macro"].skip_reason or "").lower()
    assert report["sections"]["data_health"].skipped is False


@patch("src.research.sop_orchestrator.fetch_shared_data")
@patch("src.research.sop_orchestrator.SECTION_REGISTRY", new_callable=dict)
@patch("src.research.sop_orchestrator.run_signal_backtest")
def test_missing_runner_emits_skipped(mock_bt, mock_registry, mock_fetch):
    """If a section is in SECTION_ORDER but no runner registered, get skipped."""
    from src.research.shared_data import SharedData
    mock_fetch.return_value = SharedData(
        ticker="X", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[], news=[],
        analyst_actions=[], analyst_targets=None, earnings_history=[],
        company_facts={}, sector_etf_prices=[], spy_prices=[],
    )
    mock_bt.return_value = BacktestVerdict(
        signal="x", window_start="x", window_end="x",
        n_signals=0, win_rate_20d=None, avg_return_20d=None,
        t_stat=None, significant=False, verdict="x",
    )
    # Empty registry — every section should emit skipped
    report = run_sop(_req())
    for name in SECTION_ORDER:
        assert report["sections"][name].skipped is True
        assert "no runner" in (report["sections"][name].skip_reason or "").lower()


@patch("src.research.sop_orchestrator.fetch_shared_data")
@patch("src.research.sop_orchestrator.SECTION_REGISTRY", new_callable=dict)
@patch("src.research.sop_orchestrator.run_signal_backtest")
def test_backtest_appended_to_technical_markdown(mock_bt, mock_registry, mock_fetch):
    from src.research.shared_data import SharedData
    mock_fetch.return_value = SharedData(
        ticker="X", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[], news=[],
        analyst_actions=[], analyst_targets=None, earnings_history=[],
        company_facts={}, sector_etf_prices=[], spy_prices=[],
    )
    mock_bt.return_value = BacktestVerdict(
        signal="rsi_oversold", window_start="2020-01-01",
        window_end="2026-05-22", n_signals=15, win_rate_20d=0.6,
        avg_return_20d=0.04, t_stat=2.5, significant=True,
        verdict="significant edge",
    )

    class _TechStub:
        name = "technical"
        supports_personas = []

        def run(self, ctx):
            return SectionPayload(
                name="technical",
                markdown="## Technical Analysis\n\nDaily trend up.",
                structured=None, skipped=False, persona_used=None,
            )

    mock_registry["technical"] = _TechStub()

    report = run_sop(_req(included={"technical"}))
    tech_md = report["sections"]["technical"].markdown
    assert "Backtest Validation" in tech_md
    assert "rsi_oversold" in tech_md
    assert "15" in tech_md  # n_signals
    assert "significant edge" in tech_md


@patch("src.research.sop_orchestrator.fetch_shared_data")
@patch("src.research.sop_orchestrator.SECTION_REGISTRY", new_callable=dict)
@patch("src.research.sop_orchestrator.run_signal_backtest")
@patch("src.research.sop_orchestrator.route_personas")
def test_router_runs_when_personas_on_and_assignments_stashed(
    mock_router, mock_bt, mock_registry, mock_fetch,
):
    from src.research.shared_data import SharedData
    mock_fetch.return_value = SharedData(
        ticker="X", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[], news=[],
        analyst_actions=[], analyst_targets=None, earnings_history=[],
        company_facts={}, sector_etf_prices=[], spy_prices=[],
    )
    mock_bt.return_value = BacktestVerdict(
        signal="x", window_start="x", window_end="x",
        n_signals=0, win_rate_20d=None, avg_return_20d=None,
        t_stat=None, significant=False, verdict="x",
    )
    mock_router.return_value = {
        "fundamentals": "buffett", "valuation": "graham",
        "risk_position": None, "debate": ["wood", "burry"],
        "_rationale": "tech growth tension",
    }
    # Capture what each runner sees as prior to confirm assignments stash
    captured_prior_for_debate = {}

    class _SectionStub:
        def __init__(self, name):
            self.name = name
            self.supports_personas = []

        def run(self, ctx):
            if self.name == "debate":
                captured_prior_for_debate.update(ctx.prior)
            return SectionPayload(
                name=self.name, markdown=f"## {self.name}",
                structured=None, skipped=False, persona_used=None,
            )

    for n in SECTION_ORDER:
        mock_registry[n] = _SectionStub(n)

    run_sop(_req(use_personas=True))
    mock_router.assert_called_once()
    # Magic key stashed for DebateSection
    assert "_persona_assignments" in captured_prior_for_debate
    structured = captured_prior_for_debate["_persona_assignments"].structured
    assert structured["debate"] == ["wood", "burry"]


def test_router_not_called_when_personas_off():
    """When use_personas=False, router never runs."""
    from unittest.mock import patch
    with patch("src.research.sop_orchestrator.fetch_shared_data") as mock_fetch, \
         patch("src.research.sop_orchestrator.SECTION_REGISTRY", new_callable=dict), \
         patch("src.research.sop_orchestrator.run_signal_backtest") as mock_bt, \
         patch("src.research.sop_orchestrator.route_personas") as mock_router:
        from src.research.shared_data import SharedData
        mock_fetch.return_value = SharedData(
            ticker="X", scan_date="2026-05-22",
            prices=[], financials=[], insider_trades=[], news=[],
            analyst_actions=[], analyst_targets=None, earnings_history=[],
            company_facts={}, sector_etf_prices=[], spy_prices=[],
        )
        mock_bt.return_value = BacktestVerdict(
            signal="x", window_start="x", window_end="x",
            n_signals=0, win_rate_20d=None, avg_return_20d=None,
            t_stat=None, significant=False, verdict="x",
        )
        run_sop(_req(use_personas=False))
        mock_router.assert_not_called()
