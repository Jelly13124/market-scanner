import importlib


def test_sqlite_default_has_check_same_thread(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import app.backend.database.connection as conn
    importlib.reload(conn)
    assert conn.DATABASE_URL.startswith("sqlite:///")
    assert conn.engine.url.get_backend_name() == "sqlite"


def test_postgres_url_respected(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://u:p@localhost:5432/qlab")
    import app.backend.database.connection as conn
    importlib.reload(conn)
    assert conn.engine.url.get_backend_name() == "postgresql"
    # cleanup so other tests get the sqlite default again
    monkeypatch.delenv("DATABASE_URL", raising=False)
    importlib.reload(conn)
