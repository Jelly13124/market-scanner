"""Schema smoke for ResearchReport + ResearchTradePlan SQLAlchemy classes.
These tests don't hit the DB — they verify the class structure (columns,
FK, indexes) so a typo in the model file shows up before the migration."""

from __future__ import annotations

from sqlalchemy import inspect

from app.backend.database.models import ResearchReport, ResearchTradePlan


def test_research_report_columns():
    cols = {c.name for c in inspect(ResearchReport).columns}
    expected = {
        "id", "created_at", "ticker", "scan_date",
        "request_json", "report_markdown", "rendered_html",
        "use_personas", "persona_assignments_json", "duration_seconds",
    }
    assert expected.issubset(cols), f"missing cols: {expected - cols}"


def test_research_report_indexes():
    table = ResearchReport.__table__
    index_names = {i.name for i in table.indexes}
    # Composite index for "list reports for ticker" queries
    assert "ix_research_reports_ticker_scan_date" in index_names


def test_research_trade_plan_columns():
    cols = {c.name for c in inspect(ResearchTradePlan).columns}
    expected_plan = {
        "id", "report_id",
        "direction", "entry_price", "target_price", "stop_price",
        "horizon_days", "sizing_pct", "confidence", "rationale",
    }
    expected_backtest = {
        "backtest_matches_found", "backtest_win_rate",
        "backtest_avg_pnl_pct", "backtest_sample_quality",
    }
    assert (expected_plan | expected_backtest).issubset(cols)


def test_research_trade_plan_fk_to_report():
    fks = list(inspect(ResearchTradePlan).columns["report_id"].foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "research_reports"
