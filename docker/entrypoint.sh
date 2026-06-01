#!/usr/bin/env bash
# Container entrypoint: run DB migrations ON this machine (the Fly volume is
# mounted here at /data), then exec uvicorn. Migrations live in the ENTRYPOINT —
# NOT a Fly release_command — because the release machine has no volume mounted.
set -euo pipefail

# Alembic must run from app/backend/ (where alembic.ini + the alembic/ dir live)
# with the repo root on PYTHONPATH (env.py does `from app.backend.database.models
# import Base`). env.py honors DATABASE_URL (prod: sqlite:////data/app.db).
cd /app/app/backend
PYTHONPATH=/app alembic upgrade head

# Serve the API + SPA. No --reload (Fly runs one process; reload buffers logs and
# leaks sockets). 0.0.0.0 so Fly's proxy can reach it on the internal port.
cd /app
exec uvicorn app.backend.main:app --host 0.0.0.0 --port 8000
