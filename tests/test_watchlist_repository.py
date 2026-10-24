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

_UID = 1  # Fake user_id; SQLite doesn't enforce FK constraints by default.


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
        row = repo.create("My List", user_id=_UID)
        assert row.id > 0
        assert row.name == "My List"
        assert row.tickers == []
        assert row.user_id == _UID

    def test_get_by_id_missing_returns_none(self, db_session):
        repo = UserWatchlistRepository(db_session)
        assert repo.get(99999, user_id=_UID) is None

    def test_get_cross_user_returns_none(self, db_session):
        """A row created by user 1 is invisible to user 2."""
        repo = UserWatchlistRepository(db_session)
        row = repo.create("Secret", user_id=1)
        assert repo.get(row.id, user_id=2) is None

    def test_list_returns_newest_first(self, db_session):
        repo = UserWatchlistRepository(db_session)
        repo.create("Alpha", user_id=_UID)
        # Tiny delay so created_at ordering is unambiguous on SQLite.
        time.sleep(0.01)
        repo.create("Bravo", user_id=_UID)
        rows = repo.list(user_id=_UID)
        assert len(rows) == 2
        assert rows[0].name == "Bravo"
        assert rows[1].name == "Alpha"

    def test_list_scoped_to_user(self, db_session):
        """list() only returns rows owned by the given user_id."""
        repo = UserWatchlistRepository(db_session)
        repo.create("User1 List", user_id=1)
        repo.create("User2 List", user_id=2)
        rows1 = repo.list(user_id=1)
        assert len(rows1) == 1
        assert rows1[0].name == "User1 List"

    def test_rename_via_update(self, db_session):
        repo = UserWatchlistRepository(db_session)
        row = repo.create("Old", user_id=_UID)
        updated = repo.update(row.id, user_id=_UID, name="New")
        assert updated is not None
        assert updated.name == "New"
        assert repo.get_by_name("New", user_id=_UID) is not None
        assert repo.get_by_name("Old", user_id=_UID) is None

    def test_add_remove_ticker_idempotent(self, db_session):
        repo = UserWatchlistRepository(db_session)
        row = repo.create("Tech", user_id=_UID)
        repo.add_ticker(row.id, "NVDA", user_id=_UID)
        repo.add_ticker(row.id, "nvda", user_id=_UID)  # case + dup
        repo.add_ticker(row.id, "NVDA", user_id=_UID)  # exact dup
        after_add = repo.get(row.id, user_id=_UID)
        assert after_add.tickers == ["NVDA"]

        repo.add_ticker(row.id, "AAPL", user_id=_UID)
        assert repo.get(row.id, user_id=_UID).tickers == ["NVDA", "AAPL"]

        repo.remove_ticker(row.id, "nvda", user_id=_UID)
        assert repo.get(row.id, user_id=_UID).tickers == ["AAPL"]
        # Removing a missing ticker is a no-op.
        repo.remove_ticker(row.id, "NOPE", user_id=_UID)
        assert repo.get(row.id, user_id=_UID).tickers == ["AAPL"]

    def test_delete_returns_true_or_false(self, db_session):
        repo = UserWatchlistRepository(db_session)
        row = repo.create("Doomed", user_id=_UID)
        assert repo.delete(row.id, user_id=_UID) is True
        assert repo.get(row.id, user_id=_UID) is None
        assert repo.delete(row.id, user_id=_UID) is False  # already gone

    def test_name_uniqueness_per_user_raises(self, db_session):
        """Same name + same user_id violates the unique constraint."""
        repo = UserWatchlistRepository(db_session)
        repo.create("Unique", user_id=_UID)
        with pytest.raises(IntegrityError):
            repo.create("Unique", user_id=_UID)

    def test_same_name_different_users_allowed(self, db_session):
        """Same name with different user_ids is fine (per-user uniqueness)."""
        repo = UserWatchlistRepository(db_session)
        r1 = repo.create("SharedName", user_id=1)
        r2 = repo.create("SharedName", user_id=2)
        assert r1.id != r2.id
