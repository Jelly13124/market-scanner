"""CRUD for screener_presets."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Optional
from sqlalchemy.orm import Session
from app.backend.database.models import ScreenerPreset


class ScreenerPresetRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, *, name: str, market: str | None, filters: dict,
               sort_by: str = "market_cap", sort_dir: str = "desc",
               schedule_enabled: bool = False,
               notify_channels: list[str] | None = None) -> ScreenerPreset:
        row = ScreenerPreset(
            name=name, market=market, filters_json=filters or {},
            sort_by=sort_by, sort_dir=sort_dir,
            schedule_enabled=schedule_enabled, notify_channels=notify_channels,
        )
        self.db.add(row); self.db.commit(); self.db.refresh(row)
        return row

    def get(self, preset_id: int) -> Optional[ScreenerPreset]:
        return self.db.query(ScreenerPreset).filter(
            ScreenerPreset.id == preset_id).first()

    def list(self) -> list[ScreenerPreset]:
        return self.db.query(ScreenerPreset).order_by(
            ScreenerPreset.created_at.desc(), ScreenerPreset.id.desc()).all()

    def list_enabled(self) -> list[ScreenerPreset]:
        return self.db.query(ScreenerPreset).filter(
            ScreenerPreset.schedule_enabled.is_(True)).all()

    def patch(self, preset_id: int, fields: dict[str, Any]) -> Optional[ScreenerPreset]:
        row = self.get(preset_id)
        if row is None:
            return None
        allowed = {"name", "market", "filters_json", "sort_by", "sort_dir",
                   "schedule_enabled", "notify_channels"}
        if "filters" in fields:
            fields = {**fields, "filters_json": fields.pop("filters")}
        for k, v in fields.items():
            if k in allowed:
                setattr(row, k, v)
        self.db.commit(); self.db.refresh(row)
        return row

    def delete(self, preset_id: int) -> bool:
        row = self.get(preset_id)
        if row is None:
            return False
        self.db.delete(row); self.db.commit()
        return True

    def mark_run(self, preset_id: int, *, match_count: int, when: datetime) -> None:
        row = self.get(preset_id)
        if row is None:
            return
        row.last_match_count = match_count
        row.last_run_at = when
        self.db.commit()
