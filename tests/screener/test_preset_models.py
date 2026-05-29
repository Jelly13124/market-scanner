"""ScreenerPreset ORM smoke."""
from __future__ import annotations
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.backend.database.models import Base, ScreenerPreset


@pytest.fixture()
def session():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def test_insert_minimal(session):
    p = ScreenerPreset(name="cheap tech", market="US",
                       filters_json={"pe_max": 20, "sector_in": ["Technology"]})
    session.add(p); session.commit()
    out = session.query(ScreenerPreset).one()
    assert out.name == "cheap tech"
    assert out.filters_json["pe_max"] == 20
    assert out.schedule_enabled is False
    assert out.sort_by == "market_cap"


def test_full_fields(session):
    p = ScreenerPreset(name="x", market=None, filters_json={},
                       sort_by="pe_ttm", sort_dir="asc",
                       schedule_enabled=True, notify_channels=["email"],
                       last_match_count=5)
    session.add(p); session.commit()
    out = session.query(ScreenerPreset).one()
    assert out.schedule_enabled is True
    assert out.notify_channels == ["email"]
    assert out.last_match_count == 5
