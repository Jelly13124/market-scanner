"""Phase 6D: smoke tests for new Lab SQLAlchemy classes."""

from __future__ import annotations

from sqlalchemy import inspect

from app.backend.database.models import Strategy, LabChatMessage, Backtest


def test_strategy_columns():
    cols = {c.name for c in inspect(Strategy).columns}
    expected = {"id", "created_at", "updated_at", "name", "description", "spec_json", "version"}
    assert expected.issubset(cols)


def test_strategy_name_unique():
    indexes = {i.name for i in Strategy.__table__.indexes}
    assert "ix_strategies_name" in indexes


def test_lab_chat_message_fk():
    fks = list(inspect(LabChatMessage).columns["strategy_id"].foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "strategies"


def test_backtest_has_is_oos_metric_columns():
    cols = {c.name for c in inspect(Backtest).columns}
    for prefix in ("is_", "oos_"):
        for metric in ("cagr", "sharpe", "sortino", "max_drawdown", "win_rate",
                        "profit_factor", "n_trades", "calmar", "avg_holding_days"):
            assert f"{prefix}{metric}" in cols, f"missing {prefix}{metric}"
    assert "verdict_label" in cols
    assert "verdict_text" in cols
    assert "degradation_ratio" in cols
    assert "equity_curve_is" in cols and "equity_curve_oos" in cols
    assert "trades_json" in cols
