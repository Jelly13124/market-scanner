"""SQL connection selection, independent of developer .env and live servers."""
import json
import os
import subprocess
import sys


def _connection_config(database_url=None):
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    if database_url is not None:
        env["DATABASE_URL"] = database_url
    result = subprocess.run(
        [sys.executable, "-c", '''
import json
import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: False
from app.backend.database.connection import engine
print(json.dumps({"backend": engine.url.get_backend_name(),
                  "database": engine.url.database, "host": engine.url.host,
                  "port": engine.url.port}))
engine.dispose()
'''], env=env, capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def test_default_database_is_postgresql():
    assert _connection_config() == {
        "backend": "postgresql", "database": "market_scanner",
        "host": "127.0.0.1", "port": 5433,
    }


def test_postgres_url_respected():
    config = _connection_config("postgresql+psycopg2://u:p@localhost:5432/qlab")
    assert config["backend"] == "postgresql"
    assert config["database"] == "qlab"
    assert config["port"] == 5432


def test_sqlite_requires_explicit_configuration():
    config = _connection_config("sqlite:///:memory:")
    assert config["backend"] == "sqlite"
    assert config["database"] == ":memory:"
