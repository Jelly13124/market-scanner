"""Repository for saved AnalyzeFlow templates.

Phase 5D persistence for the Analyze panel's React Flow canvas. Each row
captures the included sections + persona overrides for a named template
that the UI can save / load / delete. No business logic — routes own
that.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.backend.database.models import AnalyzeFlow


class AnalyzeFlowRepository:
    """CRUD for AnalyzeFlow."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # -- create --------------------------------------------------------------

    def create(
        self,
        *,
        name: str,
        included_sections: list[str],
        use_personas: bool = False,
        persona_overrides: dict[str, str] | None = None,
    ) -> AnalyzeFlow:
        row = AnalyzeFlow(
            name=name,
            included_sections=list(included_sections),
            use_personas=bool(use_personas),
            persona_overrides=dict(persona_overrides) if persona_overrides else None,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    # -- read ---------------------------------------------------------------

    def get(self, flow_id: int) -> Optional[AnalyzeFlow]:
        return (
            self.db.query(AnalyzeFlow)
            .filter(AnalyzeFlow.id == flow_id)
            .first()
        )

    def get_by_name(self, name: str) -> Optional[AnalyzeFlow]:
        return (
            self.db.query(AnalyzeFlow)
            .filter(AnalyzeFlow.name == name)
            .first()
        )

    def list(self, *, limit: int = 100) -> list[AnalyzeFlow]:
        return (
            self.db.query(AnalyzeFlow)
            .order_by(desc(AnalyzeFlow.updated_at), desc(AnalyzeFlow.created_at), desc(AnalyzeFlow.id))
            .limit(limit)
            .all()
        )

    # -- update -------------------------------------------------------------

    def update(
        self,
        flow_id: int,
        *,
        name: str | None = None,
        included_sections: list[str] | None = None,
        use_personas: bool | None = None,
        persona_overrides: dict[str, str] | None = None,
        clear_overrides: bool = False,
    ) -> Optional[AnalyzeFlow]:
        """Patch-style update. Only fields explicitly passed are changed.

        ``clear_overrides=True`` sets ``persona_overrides`` back to None
        (since ``persona_overrides=None`` is ambiguous with "not passed").
        """
        row = self.get(flow_id)
        if row is None:
            return None
        if name is not None:
            row.name = name
        if included_sections is not None:
            row.included_sections = list(included_sections)
        if use_personas is not None:
            row.use_personas = bool(use_personas)
        if clear_overrides:
            row.persona_overrides = None
        elif persona_overrides is not None:
            row.persona_overrides = dict(persona_overrides)
        self.db.commit()
        self.db.refresh(row)
        return row

    # -- delete -------------------------------------------------------------

    def delete(self, flow_id: int) -> bool:
        row = self.get(flow_id)
        if row is None:
            return False
        self.db.delete(row)
        self.db.commit()
        return True
