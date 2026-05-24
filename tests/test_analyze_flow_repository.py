"""AnalyzeFlowRepository CRUD tests against an in-memory SQLite DB."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backend.database.connection import Base
from app.backend.repositories.analyze_flow_repository import AnalyzeFlowRepository


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    try:
        yield sess
    finally:
        sess.close()
        engine.dispose()


class TestAnalyzeFlowRepository:
    def test_create_and_get(self, db_session):
        repo = AnalyzeFlowRepository(db_session)
        row = repo.create(
            name="quick-screen",
            included_sections=["data_health", "executive_summary"],
            use_personas=True,
            persona_overrides={"valuation": "graham"},
        )
        assert row.id > 0
        assert row.name == "quick-screen"
        assert row.included_sections == ["data_health", "executive_summary"]
        assert row.persona_overrides == {"valuation": "graham"}
        assert row.use_personas is True

        fetched = repo.get(row.id)
        assert fetched is not None
        assert fetched.name == "quick-screen"

    def test_get_missing_returns_none(self, db_session):
        repo = AnalyzeFlowRepository(db_session)
        assert repo.get(99999) is None
        assert repo.get_by_name("does-not-exist") is None

    def test_list_orders_newest_first(self, db_session):
        repo = AnalyzeFlowRepository(db_session)
        a = repo.create(name="first", included_sections=["data_health"])
        b = repo.create(name="second", included_sections=["macro"])
        rows = repo.list()
        ids = [r.id for r in rows]
        # second-created row should appear before first-created row
        assert ids.index(b.id) < ids.index(a.id)

    def test_update_patches_only_provided_fields(self, db_session):
        repo = AnalyzeFlowRepository(db_session)
        row = repo.create(
            name="orig",
            included_sections=["data_health"],
            use_personas=False,
        )
        updated = repo.update(
            row.id,
            included_sections=["macro", "sector"],
            persona_overrides={"macro": "druckenmiller"},
        )
        assert updated is not None
        # name was NOT passed → unchanged
        assert updated.name == "orig"
        # included_sections + overrides updated
        assert updated.included_sections == ["macro", "sector"]
        assert updated.persona_overrides == {"macro": "druckenmiller"}
        # use_personas was NOT passed → unchanged
        assert updated.use_personas is False

    def test_delete_removes_row(self, db_session):
        repo = AnalyzeFlowRepository(db_session)
        row = repo.create(name="to-delete", included_sections=[])
        assert repo.delete(row.id) is True
        assert repo.get(row.id) is None
        # second delete returns False
        assert repo.delete(row.id) is False
