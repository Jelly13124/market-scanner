"""Container DB bootstrap — run by docker/entrypoint.sh before uvicorn.

The schema source of truth for this app is the SQLAlchemy ORM: ``app/backend/
main.py`` calls ``Base.metadata.create_all`` on import. The Alembic chain is an
INCOMPLETE legacy overlay — some tables (e.g. ``notification_subscriptions``)
have a model but no ``create_table`` migration, and one early migration adds
``user_id`` to tables in an order that assumes they already exist. So a plain
``alembic upgrade head`` fails outright against an empty database.

So we branch on the database state:
  * fresh DB (no ``alembic_version`` table) -> build the whole schema from the
    ORM via ``create_all``, then ``alembic stamp head`` so future migrations
    apply on top.
  * existing DB (has ``alembic_version``) -> run the normal incremental
    ``upgrade head``.

Idempotent — safe to run on every boot. Honors DATABASE_URL (connection.py and
alembic/env.py both read it), so it targets whatever DB the container points at.
"""
from __future__ import annotations

import os

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.backend.database.connection import engine
from app.backend.database.models import Base  # noqa: F401 — registers every table on Base.metadata


def _alembic_config() -> Config:
    """Build an Alembic Config pointing at app/backend, resolved from this file
    so the caller's cwd doesn't matter (the entrypoint runs us from /app)."""
    here = os.path.dirname(os.path.abspath(__file__))                 # .../docker
    backend = os.path.join(os.path.dirname(here), "app", "backend")  # .../app/backend
    cfg = Config(os.path.join(backend, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(backend, "alembic"))
    return cfg


def main() -> None:
    cfg = _alembic_config()
    if "alembic_version" in inspect(engine).get_table_names():
        print("[db_init] existing DB -> alembic upgrade head", flush=True)
        command.upgrade(cfg, "head")
    else:
        print("[db_init] fresh DB -> create_all + alembic stamp head", flush=True)
        Base.metadata.create_all(bind=engine)
        command.stamp(cfg, "head")
    print("[db_init] done", flush=True)


if __name__ == "__main__":
    main()
