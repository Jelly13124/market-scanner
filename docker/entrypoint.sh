#!/usr/bin/env bash
# Container entrypoint: run DB migrations ON this machine (the Fly volume is
# mounted here at /data), then exec uvicorn. Migrations live in the ENTRYPOINT —
# NOT a Fly release_command — because the release machine has no volume mounted.
set -euo pipefail

# Initialize the schema. docker/db_init.py branches on DB state: a fresh DB is
# built from the ORM via create_all + `alembic stamp head`; an existing DB gets
# the normal incremental `alembic upgrade head`. (create_all is this app's schema
# source of truth — the alembic chain is an incomplete legacy overlay that can't
# build an empty DB on its own.) Run from /app with the repo on PYTHONPATH so the
# `app.backend...` imports resolve; connection.py + env.py honor DATABASE_URL
# (prod: sqlite:////data/app.db on the mounted volume).
cd /app
PYTHONPATH=/app python docker/db_init.py

# Serve the API + SPA. No --reload (Fly runs one process; reload buffers logs and
# leaks sockets). 0.0.0.0 so Fly's proxy can reach it on the internal port.
cd /app
exec uvicorn app.backend.main:app --host 0.0.0.0 --port 8000
