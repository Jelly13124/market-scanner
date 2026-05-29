# Postgres bring-up + migration smoke (Task 0.3)

The app reads `DATABASE_URL` (env) for both the runtime engine
(`app/backend/database/connection.py`) and Alembic (`app/backend/alembic/env.py`
honors it, falling back to the `alembic.ini` SQLite url when unset). Tests
default to SQLite; Postgres is the deployment target.

## Verify migrations on Postgres (run when Docker Desktop is running)

```powershell
# 1. Start Docker Desktop (GUI), then a Postgres 16 container:
docker run --name qlab-pg -e POSTGRES_PASSWORD=qlab -e POSTGRES_DB=qlab -p 5432:5432 -d postgres:16

# 2. Point the tooling at it and apply every migration on a fresh PG:
$env:DATABASE_URL = "postgresql+psycopg2://postgres:qlab@localhost:5432/qlab"
$env:PYTHONPATH   = "C:\Users\Jerry\Desktop\ai-hedge-fund"
Set-Location "C:\Users\Jerry\Desktop\ai-hedge-fund\app\backend"
& "C:\Users\Jerry\anaconda3\python.exe" -m alembic upgrade head   # must be clean

# 3. Confirm create_all also works on PG (dev runtime path):
Set-Location "C:\Users\Jerry\Desktop\ai-hedge-fund"
& "C:\Users\Jerry\anaconda3\python.exe" -c "from app.backend.database import engine, Base; import app.backend.database.models; Base.metadata.create_all(bind=engine); print('create_all ok')"
```

If any migration fails on PG (SQLite-only DDL, batch_alter assumptions), fix the
offending migration to be PG+SQLite compatible (`sa.BigInteger().with_variant(sa.Integer(), "sqlite")`,
avoid SQLite pragmas) and re-run step 2 until clean.

## Status

- `env.py` now honors `DATABASE_URL` (committed).
- **PG smoke deferred:** Docker Desktop engine was not running at implementation
  time (CLI present, daemon down). Run the steps above once Docker is up — this
  is the gate before the public-deployment spec. Building Waves 1–7 on SQLite in
  the meantime is expected and safe.
