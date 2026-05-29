from __future__ import annotations
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.backend.database.models import Base, ScreenerPreset
from app.backend.repositories.screener_preset_repository import ScreenerPresetRepository

UID = 1  # dummy user_id used throughout


@pytest.fixture()
def repo():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    yield ScreenerPresetRepository(db)
    db.close()


def test_create_and_get(repo):
    p = repo.create(name="a", market="US", filters={"pe_max": 30},
                    sort_by="market_cap", sort_dir="desc", user_id=UID)
    assert p.id is not None
    assert repo.get(p.id, user_id=UID).name == "a"


def test_list_and_list_enabled(repo):
    repo.create(name="off", market="US", filters={}, user_id=UID)
    on = repo.create(name="on", market="US", filters={}, schedule_enabled=True,
                     notify_channels=["email"], user_id=UID)
    assert len(repo.list(user_id=UID)) == 2
    enabled = repo.list_enabled()  # unscoped — cron path
    assert [p.id for p in enabled] == [on.id]


def test_patch(repo):
    p = repo.create(name="a", market="US", filters={}, user_id=UID)
    repo.patch(p.id, {"name": "b", "schedule_enabled": True}, user_id=UID)
    out = repo.get(p.id, user_id=UID)
    assert out.name == "b" and out.schedule_enabled is True


def test_delete(repo):
    p = repo.create(name="a", market="US", filters={}, user_id=UID)
    assert repo.delete(p.id, user_id=UID) is True
    assert repo.get(p.id, user_id=UID) is None
    assert repo.delete(999, user_id=UID) is False


def test_mark_run(repo):
    p = repo.create(name="a", market="US", filters={}, user_id=UID)
    when = datetime.now(timezone.utc)
    repo.mark_run(p.id, match_count=7, when=when)
    out = repo.get(p.id, user_id=UID)
    assert out.last_match_count == 7 and out.last_run_at is not None
