"""Phase 6D: CRUD tests for the 3 Lab repositories."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from app.backend.database.connection import Base
# Import models so SQLAlchemy registers them on Base.metadata before create_all
import app.backend.database.models  # noqa: F401
from app.backend.repositories.lab_strategy_repository import StrategyRepository
from app.backend.repositories.lab_chat_repository import LabChatRepository
from app.backend.repositories.lab_backtest_repository import BacktestRepository


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _spec_dict():
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


class TestStrategyRepository:
    def test_create_get_list_delete(self, db):
        repo = StrategyRepository(db)
        s = repo.create(name="Test", description="x", spec_json=_spec_dict(), user_id=1)
        assert s.id > 0 and s.version == 1
        loaded = repo.get(s.id, user_id=1)
        assert loaded.name == "Test"
        assert repo.list(user_id=1)[0].id == s.id
        assert repo.get_by_name("Test", user_id=1).id == s.id
        repo.delete(s.id, user_id=1)
        assert repo.get(s.id, user_id=1) is None

    def test_update_spec_bumps_version(self, db):
        repo = StrategyRepository(db)
        s = repo.create(name="V", description="", spec_json=_spec_dict(), user_id=1)
        new_spec = _spec_dict()
        new_spec["description"] = "edited"
        updated = repo.update_spec(s.id, user_id=1, spec_json=new_spec)
        assert updated.version == 2

    def test_unique_name_per_user(self, db):
        """Same user + same name → IntegrityError; different user + same name → OK."""
        repo = StrategyRepository(db)
        repo.create(name="Dup", description="", spec_json=_spec_dict(), user_id=1)
        # Same user, same name → must fail
        with pytest.raises((IntegrityError, Exception)):
            repo.create(name="Dup", description="", spec_json=_spec_dict(), user_id=1)

    def test_same_name_allowed_across_users(self, db):
        """Different users may share a strategy name (per-user uniqueness)."""
        repo = StrategyRepository(db)
        repo.create(name="Shared", description="", spec_json=_spec_dict(), user_id=1)
        s2 = repo.create(name="Shared", description="", spec_json=_spec_dict(), user_id=2)
        assert s2.id is not None

    def test_cross_user_get_returns_none(self, db):
        repo = StrategyRepository(db)
        s = repo.create(name="Mine", description="", spec_json=_spec_dict(), user_id=1)
        assert repo.get(s.id, user_id=2) is None

    def test_get_by_id_unscoped(self, db):
        repo = StrategyRepository(db)
        s = repo.create(name="Unscoped", description="", spec_json=_spec_dict(), user_id=1)
        assert repo.get_by_id_unscoped(s.id).id == s.id


class TestLabChatRepository:
    def test_add_message_and_list(self, db):
        srepo = StrategyRepository(db)
        s = srepo.create(name="ChatTest", description="", spec_json=_spec_dict(), user_id=1)
        crepo = LabChatRepository(db)
        m = crepo.add(strategy_id=s.id, role="user", content="hello", user_id=1)
        assert m.id > 0
        crepo.add(
            strategy_id=s.id, role="assistant", content="hi",
            spec_patch_json={"x": 1}, spec_snapshot_json=_spec_dict(),
            user_id=1,
        )
        messages = crepo.list_for_strategy(s.id, user_id=1, limit=20)
        assert len(messages) == 2

    def test_mark_patch_accepted(self, db):
        srepo = StrategyRepository(db)
        s = srepo.create(name="C2", description="", spec_json=_spec_dict(), user_id=1)
        crepo = LabChatRepository(db)
        m = crepo.add(
            strategy_id=s.id, role="assistant", content="patch",
            spec_patch_json={"x": 1}, spec_snapshot_json=_spec_dict(),
            user_id=1,
        )
        crepo.mark_patch_accepted(m.id, accepted=True)
        loaded = crepo.list_for_strategy(s.id, user_id=1)[0]
        assert loaded.patch_accepted is True

    def test_cross_user_messages_not_visible(self, db):
        srepo = StrategyRepository(db)
        s = srepo.create(name="ChatIso", description="", spec_json=_spec_dict(), user_id=1)
        crepo = LabChatRepository(db)
        crepo.add(strategy_id=s.id, role="user", content="secret", user_id=1)
        # User 2 should see no messages
        assert crepo.list_for_strategy(s.id, user_id=2, limit=20) == []


class TestBacktestRepository:
    def test_create_and_list(self, db):
        srepo = StrategyRepository(db)
        s = srepo.create(name="B", description="", spec_json=_spec_dict(), user_id=1)
        brepo = BacktestRepository(db)
        bt = brepo.create(
            strategy_id=s.id,
            spec_snapshot_json=_spec_dict(),
            start_date="2020-01-01", end_date="2024-12-31", midpoint_date="2023-09-08",
            universe_size=10,
            is_metrics={
                "cagr": 0.15, "sharpe": 1.2, "n_trades": 30,
                "total_return": 0.5, "sortino": 1.3, "max_drawdown": -0.1,
                "calmar": 1.5, "win_rate": 0.55, "profit_factor": 1.8,
                "avg_holding_days": 15,
            },
            oos_metrics={
                "cagr": 0.12, "sharpe": 0.9, "n_trades": 15,
                "total_return": 0.3, "sortino": 1.0, "max_drawdown": -0.15,
                "calmar": 0.8, "win_rate": 0.52, "profit_factor": 1.5,
                "avg_holding_days": 14,
            },
            degradation_ratio=0.8, benchmark_cagr=0.10,
            verdict_label="weak", verdict_text="weak edge",
            trades=[{"ticker": "NVDA", "pnl": 100}],
            equity_curve_is=[100000, 110000],
            equity_curve_oos=[110000, 115000],
            benchmark_curve=None, duration_seconds=42.5,
            user_id=1,
        )
        assert bt.id > 0
        assert brepo.get(bt.id, user_id=1).verdict_label == "weak"
        assert brepo.list_for_strategy(s.id, user_id=1)[0].id == bt.id

    def test_cross_user_backtest_not_visible(self, db):
        srepo = StrategyRepository(db)
        s = srepo.create(name="BIso", description="", spec_json=_spec_dict(), user_id=1)
        brepo = BacktestRepository(db)
        bt = brepo.create(
            strategy_id=s.id, spec_snapshot_json=_spec_dict(),
            start_date="2020-01-01", end_date="2024-12-31", midpoint_date="2023-09-08",
            universe_size=5,
            is_metrics={
                "cagr": 0.1, "sharpe": 1.0, "n_trades": 10,
                "total_return": 0.3, "sortino": 1.0, "max_drawdown": -0.1,
                "calmar": 1.0, "win_rate": 0.5, "profit_factor": 1.0,
                "avg_holding_days": 10,
            },
            oos_metrics={
                "cagr": 0.08, "sharpe": 0.8, "n_trades": 5,
                "total_return": 0.2, "sortino": 0.8, "max_drawdown": -0.12,
                "calmar": 0.7, "win_rate": 0.48, "profit_factor": 0.9,
                "avg_holding_days": 9,
            },
            degradation_ratio=0.8, benchmark_cagr=0.1,
            verdict_label="weak", verdict_text="weak",
            trades=[], equity_curve_is=[], equity_curve_oos=[],
            user_id=1,
        )
        assert brepo.get(bt.id, user_id=2) is None
