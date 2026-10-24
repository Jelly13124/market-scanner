"""Phase 4 CLI tests - run_sop + render_sop + file output."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.research.models import (
    AnalyzeRequest, BacktestVerdict, SECTION_ORDER,
    SectionPayload,
)


def _fake_report(ticker="NVDA"):
    sections = {
        n: SectionPayload(name=n, markdown=f"## {n}\n\nbody", structured=None,
                          skipped=False, persona_used=None)
        for n in SECTION_ORDER
    }
    return {
        "request": AnalyzeRequest(
            ticker=ticker, objective="medium_term",
            position_budget_usd=10000, already_holds=False, cost_basis_usd=None,
            risk_tolerance="balanced", use_personas=False,
        ),
        "sections": sections,
        "persona_assignments": None,
        "backtest": BacktestVerdict(
            signal="rsi_oversold", window_start="2020-01-01",
            window_end="2026-05-22", n_signals=10, win_rate_20d=0.6,
            avg_return_20d=0.02, t_stat=2.1, significant=True,
            verdict="significant",
        ),
        "rendered_html": None,
    }


class TestCLI:
    @patch("src.research.html_render.render_sop")
    @patch("src.research.sop_orchestrator.run_sop")
    def test_default_args_writes_tempfile(self, mock_run, mock_render, capsys, tmp_path):
        from src.research.__main__ import main
        mock_run.return_value = _fake_report("NVDA")
        mock_render.return_value = "<html><body>NVDA</body></html>"
        exit_code = main(["--ticker", "NVDA"])
        captured = capsys.readouterr()
        assert exit_code == 0
        # The stdout line is the path
        path = Path(captured.out.strip())
        assert path.exists()
        assert path.read_text(encoding="utf-8") == "<html><body>NVDA</body></html>"

    @patch("src.research.html_render.render_sop")
    @patch("src.research.sop_orchestrator.run_sop")
    def test_request_carries_all_args(self, mock_run, mock_render, capsys):
        from src.research.__main__ import main
        captured_req = {}
        def _capture(req):
            captured_req["req"] = req
            return _fake_report(req.ticker)
        mock_run.side_effect = _capture
        mock_render.return_value = "<html></html>"
        main([
            "--ticker", "nvda",
            "--objective", "short_term",
            "--budget", "5000",
            "--holds", "--cost-basis", "120.5",
            "--risk", "aggressive",
            "--use-personas",
            "--only", "macro",
            "--only", "technical",
        ])
        req = captured_req["req"]
        assert req.ticker == "NVDA"  # uppercased
        assert req.objective == "short_term"
        assert req.position_budget_usd == 5000.0
        assert req.already_holds is True
        assert req.cost_basis_usd == 120.5
        assert req.risk_tolerance == "aggressive"
        assert req.use_personas is True
        assert req.included_sections == {"macro", "technical"}

    @patch("src.research.html_render.render_sop")
    @patch("src.research.sop_orchestrator.run_sop")
    def test_stderr_summary_printed(self, mock_run, mock_render, capsys):
        from src.research.__main__ import main
        mock_run.return_value = _fake_report("NVDA")
        mock_render.return_value = "<html></html>"
        main(["--ticker", "NVDA"])
        err = capsys.readouterr().err
        assert "SECTIONS" in err
        assert "BACKTEST VERDICT" in err
        # No PERSONA ASSIGNMENTS box when no assignments
        assert "PERSONA ASSIGNMENTS" not in err
