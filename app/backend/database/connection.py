from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent
_DEFAULT_SQLITE = f"sqlite:///{BACKEND_DIR / 'hedge_fund.db'}"
DATABASE_URL = os.getenv("DATABASE_URL", _DEFAULT_SQLITE)

_IS_SQLITE = DATABASE_URL.startswith("sqlite")
# check_same_thread is a SQLite-only arg; Postgres rejects it.
_connect_args = {"check_same_thread": False} if _IS_SQLITE else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args, pool_pre_ping=True)

if _IS_SQLITE:
    # Make file-backed SQLite safe for a small multi-user/threaded deployment:
    #   WAL        — concurrent readers don't block the single writer
    #   busy_timeout — wait up to 30s for a write lock instead of raising
    #                  "database is locked" the instant two writes overlap
    # (No-ops / harmless on the in-memory test engines, which build their own.)
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - thin DBAPI hook
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close() 