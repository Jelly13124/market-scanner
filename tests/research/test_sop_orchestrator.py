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


def _req(use_personas=False, included=None, objective="medium_term"):
    return AnalyzeRequest(
        ticker="NVDA",
        objective=objective,
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
    # Every section ran. Stricter order assertion was loosened on
    # 2026-05-25 when the 10 _PARALLEL_SECTIONS started dispatching
    # via ThreadPoolExecutor (LLM I/O-bound, completion order is
    # non-deterministic). We now assert section batches in relative
    # order: pre-parallel sequential -> parallel batch -> post-parallel
    # sequential, with the parallel batch members allowed in any order.
    from src.research.sop_orchestrator import _PARALLEL_SECTIONS
    assert set(call_log) == set(SECTION_ORDER)
    pre = [n for n in SECTION_ORDER if n not in _PARALLEL_SECTIONS
           and SECTION_ORDER.index(n) < SECTION_ORDER.index("macro")]
    post = [n for n in SECTION_ORDER if n not in _PARALLEL_SECTIONS
            and SECTION_ORDER.index(n) > SECTION_ORDER.index("event_risk")]
    # Pre-parallel sections retain their SECTION_ORDER positions.
    for i, n in enumerate(pre):
        assert call_log[i] == n, f"pre-parallel position {i} should be {n}, got {call_log[i]}"
    # Parallel batch occupies indices len(pre) .. len(pre)+9 in some order.
    parallel_slice = call_log[len(pre):len(pre) + len(_PARALLEL_SECTIONS)]
    assert set(parallel_slice) == _PARALLEL_SECTIONS
    # Post-parallel sections come after, in their SECTION_ORDER positions.
    for i, n in enumerate(post):
        assert call_log[len(pre) + len(_PARALLEL_SECTIONS) + i] == n
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


# ---------------------------------------------------------------------------
# Phase 10 Wave 2: intraday K-line gating
# ---------------------------------------------------------------------------


def _empty_shared():
    from src.research.shared_data import SharedData
    return SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[], news=[],
        analyst_actions=[], analyst_targets=None, earnings_history=[],
        company_facts={}, sector_etf_prices=[], spy_prices=[],
    )


class _TechStub:
    name = "technical"
    supports_personas = []

    def run(self, ctx):
        return SectionPayload(
            name="technical", markdown="## Technical Analysis\n\nbody.",
            structured=None, skipped=False, persona_used=None,
        )


@patch("src.research.sop_orchestrator.fetch_shared_data")
@patch("src.research.sop_orchestrator.SECTION_REGISTRY", new_callable=dict)
@patch("src.research.sop_orchestrator.run_signal_backtest")
@patch("src.research.sop_orchestrator.png_to_b64_uri", return_value="data:image/png;base64,AAA")
@patch("src.research.sop_orchestrator.render_intraday_png", return_value=b"\x89PNG")
@patch("src.research.sop_orchestrator.fetch_intraday_prices")
def test_short_term_objective_fetches_and_adds_intraday(
    mock_fetch_intraday, mock_render, mock_b64, mock_bt, mock_registry, mock_fetch,
):
    from v2.data.models import Price
    mock_fetch.return_value = _empty_shared()
    mock_bt.return_value = BacktestVerdict(
        signal="x", window_start="x", window_end="x", n_signals=0,
        win_rate_20d=None, avg_return_20d=None, t_stat=None,
        significant=False, verdict="x",
    )
    mock_fetch_intraday.return_value = [
        Price(open=1.0, high=2.0, low=0.5, close=1.5, volume=10, time="2026-05-29T09:30:00"),
        Price(open=1.5, high=2.5, low=1.0, close=2.0, volume=20, time="2026-05-29T09:35:00"),
    ]
    mock_registry["technical"] = _TechStub()

    report = run_sop(_req(included={"technical"}, objective="short_term"))

    # Fetcher called with the short_term window (5d / 5m).
    mock_fetch_intraday.assert_called_once()
    _, kwargs = mock_fetch_intraday.call_args
    assert kwargs.get("period") == "5d"
    assert kwargs.get("interval") == "5m"

    structured = report["sections"]["technical"].structured
    assert isinstance(structured, dict)
    assert structured.get("chart_kline_intraday_b64") == "data:image/png;base64,AAA"


@patch("src.research.sop_orchestrator.fetch_shared_data")
@patch("src.research.sop_orchestrator.SECTION_REGISTRY", new_callable=dict)
@patch("src.research.sop_orchestrator.run_signal_backtest")
@patch("src.research.sop_orchestrator.fetch_intraday_prices")
def test_long_term_objective_does_not_fetch_intraday(
    mock_fetch_intraday, mock_bt, mock_registry, mock_fetch,
):
    mock_fetch.return_value = _empty_shared()
    mock_bt.return_value = BacktestVerdict(
        signal="x", window_start="x", window_end="x", n_signals=0,
        win_rate_20d=None, avg_return_20d=None, t_stat=None,
        significant=False, verdict="x",
    )
    mock_registry["technical"] = _TechStub()

    report = run_sop(_req(included={"technical"}, objective="long_term"))

    # Non-qualifying objective: fetcher never called, key absent.
    mock_fetch_intraday.assert_not_called()
    structured = report["sections"]["technical"].structured
    if isinstance(structured, dict):
        assert "chart_kline_intraday_b64" not in structured


@patch("src.research.sop_orchestrator.fetch_shared_data")
@patch("src.research.sop_orchestrator.SECTION_REGISTRY", new_callable=dict)
@patch("src.research.sop_orchestrator.run_signal_backtest")
@patch("src.research.sop_orchestrator.png_to_b64_uri", return_value="data:image/png;base64,BBB")
@patch("src.research.sop_orchestrator.render_intraday_png", return_value=b"\x89PNG")
@patch("src.research.sop_orchestrator.fetch_intraday_prices")
def test_earnings_review_uses_15m_window(
    mock_fetch_intraday, mock_render, mock_b64, mock_bt, mock_registry, mock_fetch,
):
    mock_fetch.return_value = _empty_shared()
    mock_bt.return_value = BacktestVerdict(
        signal="x", window_start="x", window_end="x", n_signals=0,
        win_rate_20d=None, avg_return_20d=None, t_stat=None,
        significant=False, verdict="x",
    )
    # Empty intraday -> no chart, but fetch still invoked with the window.
    mock_fetch_intraday.return_value = []
    mock_registry["technical"] = _TechStub()

    run_sop(_req(included={"technical"}, objective="earnings_review"))

    mock_fetch_intraday.assert_called_once()
    _, kwargs = mock_fetch_intraday.call_args
    assert kwargs.get("period") == "1mo"
    assert kwargs.get("interval") == "15m"
    # Render skipped because the fetch returned no bars.
    mock_render.assert_not_called()
