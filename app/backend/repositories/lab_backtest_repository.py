"""Phase 6D: Backtest CRUD repository.

Wave 4: ``get`` and ``list_for_strategy`` are scoped by ``user_id``;
``create`` sets ``user_id`` so new backtests are owned.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.backend.database.models import Backtest


class BacktestRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        strategy_id: int,
        spec_snapshot_json: dict,
        start_date: str,
        end_date: str,
        midpoint_date: str,
        universe_size: int,
        is_metrics: dict,
        oos_metrics: dict,
        degradation_ratio: float | None,
        benchmark_cagr: float | None,
        verdict_label: str,
        verdict_text: str,
        trades: list,
        equity_curve_is: list,
        equity_curve_oos: list,
        user_id: int,
        benchmark_curve: list | None = None,
        duration_seconds: float | None = None,
        error_message: str | None = None,
    ) -> Backtest:
        bt = Backtest(
            strategy_id=strategy_id,
            spec_snapshot_json=spec_snapshot_json,
            start_date=start_date,
            end_date=end_date,
            midpoint_date=midpoint_date,
            universe_size=universe_size,
            **{f"is_{k}": v for k, v in is_metrics.items()},
            **{f"oos_{k}": v for k, v in oos_metrics.items()},
            degradation_ratio=degradation_ratio,
            benchmark_cagr=benchmark_cagr,
            verdict_label=verdict_label,
            verdict_text=verdict_text,
            trades_json=trades,
            equity_curve_is=equity_curve_is,
            equity_curve_oos=equity_curve_oos,
            benchmark_curve=benchmark_curve,
            duration_seconds=duration_seconds,
            error_message=error_message,
            user_id=user_id,
        )
        self.db.add(bt)
        self.db.commit()
        self.db.refresh(bt)
        return bt

    def get(self, backtest_id: int, *, user_id: int) -> Optional[Backtest]:
        return (
            self.db.query(Backtest)
            .filter(Backtest.id == backtest_id, Backtest.user_id == user_id)
            .first()
        )

    def list_for_strategy(
        self, strategy_id: int, *, user_id: int, limit: int = 50,
    ) -> list[Backtest]:
        return (
            self.db.query(Backtest)
            .filter(Backtest.strategy_id == strategy_id, Backtest.user_id == user_id)
            .order_by(desc(Backtest.created_at), desc(Backtest.id))
            .limit(limit)
            .all()
        )
