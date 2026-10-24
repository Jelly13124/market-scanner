"""Phase 6E: API schemas — request/response shapes for /lab/* routes."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.backend.models.lab_schemas import (
    BacktestResponse,
    BacktestRunRequest,
    ChatMessageResponse,
    ChatResponse,
    ChatSendRequest,
    StrategyCreateRequest,
    StrategyResponse,
    StrategyUpdateRequest,
)


def _spec():
    return {
        "name": "X", "description": "",
        "universe": {"kind": "sp500"},
        "entry": {"combiner": "and", "signals": [
            {"type": "ma_cross", "fast": 50, "slow": 200, "direction": "golden"}
        ]},
        "exit": [{"type": "stop_loss", "mode": "pct", "value": 0.05}],
        "filters": [], "sizing": {"type": "fixed_pct", "pct": 0.05},
        "backtest_config": {},
    }


def test_strategy_create_request_validates_name():
    r = StrategyCreateRequest(name="Test", description="x")
    assert r.name == "Test"
    with pytest.raises(ValidationError):
        StrategyCreateRequest(name="")  # empty rejected


def test_chat_send_request():
    r = ChatSendRequest(message="hello")
    assert r.message == "hello"


def test_strategy_response_from_orm_attributes():
    row = SimpleNamespace(
        id=1, name="X", description="", spec_json=_spec(),
        version=1, created_at=datetime(2026, 5, 25), updated_at=None,
    )
    r = StrategyResponse.model_validate(row, from_attributes=True)
    assert r.id == 1
    assert r.spec_json["name"] == "X"


def test_backtest_response_from_orm_attributes():
    row = SimpleNamespace(
        id=5, strategy_id=1, created_at=datetime(2026, 5, 25),
        spec_snapshot_json=_spec(),
        start_date="2020-01-01", end_date="2024-12-31", midpoint_date="2023-09-08",
        universe_size=20,
        is_total_return=0.5, is_cagr=0.15, is_sharpe=1.2, is_sortino=1.3,
        is_max_drawdown=-0.1, is_calmar=1.5, is_win_rate=0.55,
        is_profit_factor=1.8, is_n_trades=30, is_avg_holding_days=15,
        oos_total_return=0.3, oos_cagr=0.12, oos_sharpe=0.9, oos_sortino=1.0,
        oos_max_drawdown=-0.15, oos_calmar=0.8, oos_win_rate=0.52,
        oos_profit_factor=1.5, oos_n_trades=15, oos_avg_holding_days=14,
        degradation_ratio=0.8, benchmark_cagr=0.10,
        verdict_label="weak", verdict_text="ok",
        trades_json=[], equity_curve_is=[], equity_curve_oos=[],
        benchmark_curve=None, duration_seconds=42.5, error_message=None,
    )
    r = BacktestResponse.model_validate(row, from_attributes=True)
    assert r.id == 5
    assert r.verdict_label == "weak"
