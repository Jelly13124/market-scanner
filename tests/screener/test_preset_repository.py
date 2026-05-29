from __future__ import annotations
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.backend.database.models import Base, ScreenerPreset
from app.backend.repositories.screener_preset_repository import ScreenerPresetRepository


@pytest.fixture()
def repo():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    yield ScreenerPresetRepository(db)
    db.close()


def test_create_and_get(repo):
    p = repo.create(name="a", market="US", filters={"pe_max": 30},
                    sort_by="market_cap", sort_dir="desc")
    assert p.id is not None
    assert repo.get(p.id).name == "a"


def test_list_and_list_enabled(repo):
    repo.create(name="off", market="US", filters={})
    on = repo.create(name="on", market="US", filters={}, schedule_enabled=True,
                     notify_channels=["email"])
    assert len(repo.list()) == 2
    enabled = repo.list_enabled()
    assert [p.id for p in enabled] == [on.id]


def test_patch(repo):
    p = repo.create(name="a", market="US", filters={})
    repo.patch(p.id, {"name": "b", "schedule_enabled": True})
    out = repo.get(p.id)
    assert out.name == "b" and out.schedule_enabled is True


def test_delete(repo):
    p = repo.create(name="a", market="US", filters={})
    assert repo.delete(p.id) is True
    assert repo.get(p.id) is None
    assert repo.delete(999) is False


def test_mark_run(repo):
    p = repo.create(name="a", market="US", filters={})
    when = datetime.now(timezone.utc)
    repo.mark_run(p.id, match_count=7, when=when)
    out = repo.get(p.id)
    assert out.last_match_count == 7 and out.last_run_at is not None
