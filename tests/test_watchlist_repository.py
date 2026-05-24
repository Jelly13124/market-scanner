"""UserWatchlistRepository tests (Phase 5B). In-memory SQLite fixture."""

from __future__ import annotations

import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.backend.database.connection import Base
from app.backend.database.models import UserWatchlist  # noqa: F401  (registers table)
from app.backend.repositories.watchlist_repository import UserWatchlistRepository


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


class TestUserWatchlistRepository:
    def test_create_returns_row_with_id(self, db_session):
        repo = UserWatchlistRepository(db_session)
        row = repo.create("My List")
        assert row.id > 0
        assert row.name == "My List"
        assert row.tickers == []

    def test_get_by_id_missing_returns_none(self, db_session):
        repo = UserWatchlistRepository(db_session)
        assert repo.get(99999) is None

    def test_list_returns_newest_first(self, db_session):
        repo = UserWatchlistRepository(db_session)
        repo.create("Alpha")
        # Tiny delay so created_at ordering is unambiguous on SQLite.
        time.sleep(0.01)
        repo.create("Bravo")
        rows = repo.list()
        assert len(rows) == 2
        assert rows[0].name == "Bravo"
        assert rows[1].name == "Alpha"

    def test_rename_via_update(self, db_session):
        repo = UserWatchlistRepository(db_session)
        row = repo.create("Old")
        updated = repo.update(row.id, name="New")
        assert updated is not None
        assert updated.name == "New"
        assert repo.get_by_name("New") is not None
        assert repo.get_by_name("Old") is None

    def test_add_remove_ticker_idempotent(self, db_session):
        repo = UserWatchlistRepository(db_session)
        row = repo.create("Tech")
        repo.add_ticker(row.id, "NVDA")
        repo.add_ticker(row.id, "nvda")  # case + dup
        repo.add_ticker(row.id, "NVDA")  # exact dup
        after_add = repo.get(row.id)
        assert after_add.tickers == ["NVDA"]

        repo.add_ticker(row.id, "AAPL")
        assert repo.get(row.id).tickers == ["NVDA", "AAPL"]

        repo.remove_ticker(row.id, "nvda")
        assert repo.get(row.id).tickers == ["AAPL"]
        # Removing a missing ticker is a no-op.
        repo.remove_ticker(row.id, "NOPE")
        assert repo.get(row.id).tickers == ["AAPL"]

    def test_delete_returns_true_or_false(self, db_session):
        repo = UserWatchlistRepository(db_session)
        row = repo.create("Doomed")
        assert repo.delete(row.id) is True
        assert repo.get(row.id) is None
        assert repo.delete(row.id) is False  # already gone

    def test_name_uniqueness_raises(self, db_session):
        repo = UserWatchlistRepository(db_session)
        repo.create("Unique")
        with pytest.raises(IntegrityError):
            repo.create("Unique")
