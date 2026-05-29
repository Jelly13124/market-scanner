"""Phase 6D: Strategy CRUD repository.

Wave 4: every method is scoped by ``user_id`` so rows from one user are
never visible to another.  ``get_by_id_unscoped`` is provided for internal
system callers (e.g. backtest engine) that resolve a strategy by PK without
an HTTP user context.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.backend.database.models import Strategy


class StrategyRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, *, name: str, description: str, spec_json: dict, user_id: int) -> Strategy:
        s = Strategy(name=name, description=description, spec_json=spec_json, version=1, user_id=user_id)
        self.db.add(s)
        self.db.commit()
        self.db.refresh(s)
        return s

    def get(self, strategy_id: int, *, user_id: int) -> Optional[Strategy]:
        return (
            self.db.query(Strategy)
            .filter(Strategy.id == strategy_id, Strategy.user_id == user_id)
            .first()
        )

    def get_by_id_unscoped(self, strategy_id: int) -> Optional[Strategy]:
        """Unscoped lookup by primary key — for internal system use only (e.g. backtest engine).

        Do NOT call this from HTTP routes; use ``get(id, user_id=...)`` there.
        """
        return self.db.query(Strategy).filter(Strategy.id == strategy_id).first()

    def get_by_name(self, name: str, *, user_id: int) -> Optional[Strategy]:
        return (
            self.db.query(Strategy)
            .filter(Strategy.name == name, Strategy.user_id == user_id)
            .first()
        )

    def list(self, *, user_id: int, limit: int = 100) -> list[Strategy]:
        return (
            self.db.query(Strategy)
            .filter(Strategy.user_id == user_id)
            .order_by(desc(Strategy.updated_at), desc(Strategy.id))
            .limit(limit)
            .all()
        )

    def update_spec(
        self,
        strategy_id: int,
        *,
        user_id: int,
        spec_json: dict,
        description: str | None = None,
    ) -> Optional[Strategy]:
        s = self.get(strategy_id, user_id=user_id)
        if s is None:
            return None
        s.spec_json = spec_json
        s.version = (s.version or 1) + 1
        if description is not None:
            s.description = description
        self.db.commit()
        self.db.refresh(s)
        return s

    def rename(self, strategy_id: int, new_name: str, *, user_id: int) -> Optional[Strategy]:
        s = self.get(strategy_id, user_id=user_id)
        if s is None:
            return None
        s.name = new_name
        self.db.commit()
        self.db.refresh(s)
        return s

    def delete(self, strategy_id: int, *, user_id: int) -> bool:
        s = self.get(strategy_id, user_id=user_id)
        if s is None:
            return False
        self.db.delete(s)
        self.db.commit()
        return True
