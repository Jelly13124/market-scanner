"""Phase 6D: LabChatMessage CRUD repository.

Wave 4: list_for_strategy and get are scoped by ``user_id`` (via the
``lab_chat_messages.user_id`` column that was added in Wave 3). The
``add`` method sets ``user_id`` on create so new messages are owned.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.backend.database.models import LabChatMessage


class LabChatRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(
        self,
        *,
        strategy_id: int,
        role: str,
        content: str,
        user_id: int,
        spec_patch_json: dict | None = None,
        spec_snapshot_json: dict | None = None,
        patch_accepted: bool | None = None,
    ) -> LabChatMessage:
        m = LabChatMessage(
            strategy_id=strategy_id,
            role=role,
            content=content,
            spec_patch_json=spec_patch_json,
            spec_snapshot_json=spec_snapshot_json,
            patch_accepted=patch_accepted,
            user_id=user_id,
        )
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return m

    def get(self, message_id: int, *, user_id: int) -> Optional[LabChatMessage]:
        return (
            self.db.query(LabChatMessage)
            .filter(LabChatMessage.id == message_id, LabChatMessage.user_id == user_id)
            .first()
        )

    def list_for_strategy(
        self, strategy_id: int, *, user_id: int, limit: int = 50,
    ) -> list[LabChatMessage]:
        return (
            self.db.query(LabChatMessage)
            .filter(LabChatMessage.strategy_id == strategy_id, LabChatMessage.user_id == user_id)
            .order_by(desc(LabChatMessage.created_at), desc(LabChatMessage.id))
            .limit(limit)
            .all()
        )

    def mark_patch_accepted(
        self, message_id: int, *, accepted: bool,
    ) -> Optional[LabChatMessage]:
        # Unscoped — called only after get() already verified ownership.
        m = self.db.query(LabChatMessage).filter(LabChatMessage.id == message_id).first()
        if m is None:
            return None
        m.patch_accepted = accepted
        self.db.commit()
        self.db.refresh(m)
        return m
