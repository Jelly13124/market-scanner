"""Isolation tests: backtests are scoped per user_id."""

from unittest.mock import patch

from tests.auth.conftest import auth_header

_STRATEGY = {"name": "BT Strategy", "description": "test"}


def _spec_dict():
    return {
        "name": "BT Strategy", "description": "",
        "universe": {"kind": "sp500"},
        "entry": {"combiner": "and", "signals": [
            {"type": "ma_cross", "fast": 50, "slow": 200, "direction": "golden"}
        ]},
        "exit": [{"type": "stop_loss", "mode": "pct", "value": 0.05}],
        "filters": [], "sizing": {"type": "fixed_pct", "pct": 0.05},
        "backtest_config": {},
    }


def _mock_result():
    from src.lab.backtest_runner import BacktestRunResult
    from src.lab.engine.metrics import Metrics
    from src.lab.engine.verdict import Verdict

    return BacktestRunResult(
        spec_snapshot=_spec_dict(),
        start_date="2020-01-01", end_date="2024-12-31", midpoint_date="2023-09-08",
        universe_size=10,
        is_metrics=Metrics(0.5, 0.15, 1.2, 1.3, -0.1, 1.5, 0.55, 1.8, 15, 30, 0.7),
        oos_metrics=Metrics(0.3, 0.12, 0.9, 1.0, -0.15, 0.8, 0.52, 1.5, 14, 15, 0.6),
        benchmark_cagr=0.10,
        verdict=Verdict(label="weak", text="weak edge", degradation_ratio=0.8),
        equity_curve_is=[100000, 110000], equity_curve_oos=[110000, 115000],
        is_trades=[], oos_trades=[],
        duration_seconds=1.0,
    )


def test_backtest_isolation(full_client, two_users):
    a, b = two_users

    # A creates a strategy and runs a backtest
    r = full_client.post("/lab/strategies", json=_STRATEGY, headers=auth_header(a))
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    with patch("app.backend.routes.lab.run_backtest") as mock_run:
        mock_run.return_value = _mock_result()
        bt_r = full_client.post(f"/lab/strategies/{sid}/backtest", json={}, headers=auth_header(a))
    assert bt_r.status_code == 200, bt_r.text
    bt_id = bt_r.json()["id"]

    # B cannot list backtests under A's strategy → 404 (strategy not found for B)
    assert full_client.get(
        f"/lab/strategies/{sid}/backtests", headers=auth_header(b)
    ).status_code == 404

    # B cannot get A's backtest by id → 404
    assert full_client.get(
        f"/lab/backtests/{bt_id}", headers=auth_header(b)
    ).status_code == 404

    # A can still get their own backtest
    assert full_client.get(f"/lab/backtests/{bt_id}", headers=auth_header(a)).status_code == 200

    # A's list includes the backtest
    bt_list = full_client.get(f"/lab/strategies/{sid}/backtests", headers=auth_header(a)).json()
    assert any(bt["id"] == bt_id for bt in bt_list)


def test_backtest_requires_auth(full_client, two_users):
    a, _ = two_users
    r = full_client.post("/lab/strategies", json=_STRATEGY, headers=auth_header(a))
    sid = r.json()["id"]
    assert full_client.get(f"/lab/strategies/{sid}/backtests").status_code == 401
    assert full_client.get("/lab/backtests/1").status_code == 401
