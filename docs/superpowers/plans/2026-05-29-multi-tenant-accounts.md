# Multi-Tenant Accounts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the single-user app into a multi-tenant one — users register/log in (email+password or Google/GitHub OAuth) and each sees only their own data, using their own API keys.

**Architecture:** Hand-rolled sync auth (`passlib` + `python-jose` + `authlib`) on the existing sync-SQLAlchemy FastAPI app; a `users`/`oauth_accounts` model; `user_id` added to every top-level user-owned table with all queries scoped by the authenticated user; SQLite→Postgres for the deployed multi-user target. Frontend gains an `AuthProvider` + a conditional login gate (no router exists — the app is a single mounted `<App/>`).

**Tech Stack:** FastAPI (sync), SQLAlchemy 2.x, Alembic, SQLite with WAL (Postgres optional later via `DATABASE_URL`), passlib[bcrypt], python-jose[cryptography], authlib; React + Vite + TypeScript, react-i18next.

> **DB decision revised 2026-05-29:** staying on SQLite (WAL + busy_timeout) — sufficient for a few friends and far simpler to deploy/back up. The Wave-0 `DATABASE_URL` plumbing means Postgres is a 1-env-var switch if scale ever demands it, so no work is wasted. Wave 0 Task 0.3's "PG smoke" becomes optional/future; migrations still author PG-safe DDL (cheap insurance).

**Source spec:** `docs/superpowers/specs/2026-05-29-multi-tenant-accounts-design.md`

---

## Constraints (every task inherits these)

- **Python:** `C:\Users\Jerry\anaconda3\python.exe`; tests via `-m pytest`. Set `$env:PYTHONIOENCODING="utf-8"` for non-ASCII output.
- **Frontend typecheck:** from `app/frontend/`, `node node_modules/typescript/bin/tsc --noEmit` (npm is NOT on the non-interactive PATH).
- **Alembic:** run from `app/backend/` with `PYTHONPATH=C:\Users\Jerry\Desktop\ai-hedge-fund`; invoke `C:\Users\Jerry\anaconda3\python.exe -m alembic`.
- **Commits:** one per task; conventional message; **NO `Co-Authored-By:` trailer**; never `--no-verify` (git-guard hook enforces). The python-format (black, line-length 420) hook auto-runs on edited `.py`.
- **Migrations:** additive + non-destructive only. New PK `id = BigInteger().with_variant(Integer(), "sqlite")`. `down_revision` chains from the current head — check with `alembic heads` before authoring.
- **Tenancy invariant (load-bearing):** every read/write of a user-owned table MUST filter by `user_id` from the authenticated user. Each scoping task ships a **cross-tenant isolation test** (user A cannot see/modify user B's rows). A missing filter is a data leak.
- **Tests default to SQLite** (fast, the existing 934-test suite); Postgres compatibility is verified by the migration smoke task. Backend green + frontend tsc clean before each commit.
- **No secrets in code/repo:** JWT secret, OAuth client id/secret, `DATABASE_URL` all come from `.env` (gitignored). Never log them.

---

## File Structure

**New backend files**
- `app/backend/auth/security.py` — password hashing + JWT create/verify (pure functions).
- `app/backend/auth/dependencies.py` — `get_current_user` / `get_current_user_optional` FastAPI deps.
- `app/backend/auth/oauth.py` — authlib client config + sync provider token/userinfo exchange.
- `app/backend/repositories/user_repository.py` — user + oauth_account CRUD.
- `app/backend/routes/auth.py` — `/auth/*` routes.
- `app/backend/models/auth_schemas.py` — Pydantic register/login/token/user schemas.

**Modified backend files**
- `app/backend/database/connection.py` — `DATABASE_URL` from env; sqlite-only connect_args.
- `app/backend/database/models.py` — `User`, `OAuthAccount`; `user_id` on top-level user-owned tables.
- `app/backend/routes/__init__.py` — include `auth_router`.
- `app/backend/main.py` — CORS from env; JWT secret presence check.
- every user-owned repository + route (Wave 4) — `user_id` scoping.
- `app/backend/services/api_key_service.py` + callers (Wave 5) — per-user key resolution.
- `app/backend/services/scheduler_service.py` (Wave 6) — per-user opt-in cron bodies.
- `pyproject.toml` — new deps.

**New frontend files**
- `src/services/auth-service.ts` — login/register/refresh/logout/me/oauth client.
- `src/contexts/auth-context.tsx` — `AuthProvider` + `useAuth`.
- `src/lib/api-client.ts` — fetch wrapper attaching the access token + 401→refresh→retry.
- `src/components/auth/login-page.tsx` — login/register form + OAuth buttons.
- `src/components/auth/user-menu.tsx` — header name + logout.
- `src/types/auth.ts` — `User`, `TokenResponse` types.

**Modified frontend files**
- `src/main.tsx` — wrap `<App/>` with `<AuthProvider>`.
- `src/App.tsx` — conditional gate: unauthenticated → `<LoginPage/>`, else existing layout.
- existing services (Wave 7) — route fetches through `api-client`.
- `src/i18n/locales/{en,zh}.json` — `auth.*` keys.

---

## WAVE 0 — Postgres foundation

### Task 0.1: Add auth + Postgres dependencies

**Files:** Modify `pyproject.toml`

- [ ] **Step 1: Add dependencies** under `[tool.poetry.dependencies]`:

```toml
# Multi-tenant auth
passlib = {extras = ["bcrypt"], version = "^1.7.4"}
python-jose = {extras = ["cryptography"], version = "^3.3.0"}
authlib = "^1.3.0"
psycopg2-binary = "^2.9.9"
```

- [ ] **Step 2: Install** — `C:\Users\Jerry\anaconda3\python.exe -m pip install "passlib[bcrypt]" "python-jose[cryptography]" authlib psycopg2-binary`
- [ ] **Step 3: Verify imports** — `C:\Users\Jerry\anaconda3\python.exe -c "import passlib.hash, jose.jwt, authlib, psycopg2; print('ok')"` → prints `ok`.
- [ ] **Step 4: Commit** — `git add pyproject.toml && git commit -m "chore(auth): add passlib, python-jose, authlib, psycopg2 deps"`

### Task 0.2: DATABASE_URL from env (sqlite fallback)

**Files:** Modify `app/backend/database/connection.py`; Test `tests/auth/test_connection_env.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/auth/test_connection_env.py
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
```

- [ ] **Step 2: Run → FAIL** (`postgres_url_respected` fails; current code hardcodes sqlite).
  `C:\Users\Jerry\anaconda3\python.exe -m pytest tests/auth/test_connection_env.py -q`
- [ ] **Step 3: Implement** — replace the hardcoded URL/engine block:

```python
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).parent.parent
_DEFAULT_SQLITE = f"sqlite:///{BACKEND_DIR / 'hedge_fund.db'}"
DATABASE_URL = os.getenv("DATABASE_URL", _DEFAULT_SQLITE)

# check_same_thread is a SQLite-only arg; Postgres rejects it.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 4: Run → PASS** (both tests). Also run `pytest tests/ -q` to confirm no regression (still SQLite by default).
- [ ] **Step 5: Commit** — `git commit -am "feat(db): read DATABASE_URL from env, sqlite-only connect_args"`

### Task 0.3: Postgres migration smoke (compat check)

**Files:** New `docs/superpowers/notes/postgres-bringup.md` (commands); no app code unless a migration needs a PG fix.

- [ ] **Step 1:** Start a local Postgres: `docker run --name qlab-pg -e POSTGRES_PASSWORD=qlab -e POSTGRES_DB=qlab -p 5432:5432 -d postgres:16`
- [ ] **Step 2:** `$env:DATABASE_URL="postgresql+psycopg2://postgres:qlab@localhost:5432/qlab"`; from `app/backend/` with `PYTHONPATH` set: `C:\Users\Jerry\anaconda3\python.exe -m alembic upgrade head`.
- [ ] **Step 3:** If any migration fails on PG (SQLite-only DDL, `batch_alter_table` assumptions, etc.), fix the offending migration to be PG+SQLite compatible (use `sa.BigInteger().with_variant(sa.Integer(), "sqlite")`, avoid SQLite-only pragmas). Re-run until `alembic upgrade head` is clean on PG.
- [ ] **Step 4:** Verify `Base.metadata.create_all` also works on PG: `python -c "import os; os.environ['DATABASE_URL']='postgresql+psycopg2://postgres:qlab@localhost:5432/qlab'; from app.backend.database import engine, Base; from app.backend.database import models; Base.metadata.create_all(bind=engine); print('create_all ok')"`.
- [ ] **Step 5: Commit** any migration fixes — `git commit -am "fix(alembic): Postgres-compatible DDL across existing migrations"`. (If no fixes were needed, commit the bringup note: `git add docs/superpowers/notes/postgres-bringup.md && git commit -m "docs: Postgres local bringup steps"`.)

---

## WAVE 1 — Auth core (email + password)

### Task 1.1: User + OAuthAccount models + migration

**Files:** Modify `app/backend/database/models.py`; migration `app/backend/alembic/versions/<sha>_add_users_oauth.py`; Test `tests/auth/test_user_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/auth/test_user_models.py
from app.backend.database.models import User, OAuthAccount

def test_user_columns():
    cols = {c.name for c in User.__table__.columns}
    assert {"id", "email", "hashed_password", "full_name", "is_active", "is_superuser", "created_at"} <= cols

def test_oauth_unique_constraint():
    uqs = [c for c in OAuthAccount.__table__.constraints if "provider" in {col.name for col in getattr(c, "columns", [])}]
    assert uqs, "expected a unique constraint over (provider, provider_account_id)"
```

- [ ] **Step 2: Run → FAIL** (models don't exist).
- [ ] **Step 3: Implement** — append to `models.py`:

```python
class User(Base):
    __tablename__ = "users"
    id = Column(BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=True)  # null = OAuth-only
    full_name = Column(String(120))
    is_active = Column(Boolean, nullable=False, server_default=text("1"))
    is_superuser = Column(Boolean, nullable=False, server_default=text("0"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class OAuthAccount(Base):
    __tablename__ = "oauth_accounts"
    id = Column(BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True)
    user_id = Column(BigInteger().with_variant(Integer(), "sqlite"), ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String(16), nullable=False)         # 'google' | 'github'
    provider_account_id = Column(String(128), nullable=False)
    email = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("provider", "provider_account_id", name="uq_oauth_provider_account"),)
```

(Confirm `ForeignKey`, `UniqueConstraint`, `Boolean`, `text` are imported at the top of `models.py`; add to the existing `from sqlalchemy import ...` if missing.)

- [ ] **Step 4: Author migration** — `alembic revision -m "add users and oauth_accounts"`; in `upgrade()` create both tables (mirror the columns above, `id` via `sa.BigInteger().with_variant(sa.Integer(), "sqlite")`); `downgrade()` drops both. `down_revision` = current `alembic heads`.
- [ ] **Step 5: Run → PASS**; `alembic upgrade head` clean on SQLite; `pytest tests/auth/test_user_models.py -q`.
- [ ] **Step 6: Commit** — `git commit -am "feat(auth): User + OAuthAccount models + migration"`

### Task 1.2: Password hashing

**Files:** Create `app/backend/auth/__init__.py`, `app/backend/auth/security.py`; Test `tests/auth/test_security_password.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/auth/test_security_password.py
from app.backend.auth.security import hash_password, verify_password

def test_hash_and_verify():
    h = hash_password("s3cret")
    assert h != "s3cret"
    assert verify_password("s3cret", h) is True
    assert verify_password("wrong", h) is False
```

- [ ] **Step 2: Run → FAIL**.
- [ ] **Step 3: Implement** `security.py` (password half):

```python
from passlib.context import CryptContext
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
def hash_password(raw: str) -> str: return _pwd.hash(raw)
def verify_password(raw: str, hashed: str) -> bool:
    try: return _pwd.verify(raw, hashed)
    except Exception: return False
```

- [ ] **Step 4: Run → PASS**.
- [ ] **Step 5: Commit** — `git commit -am "feat(auth): bcrypt password hashing"`

### Task 1.3: JWT create/verify

**Files:** Modify `app/backend/auth/security.py`; Test `tests/auth/test_security_jwt.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/auth/test_security_jwt.py
import pytest
from app.backend.auth.security import create_access_token, create_refresh_token, decode_token

def test_roundtrip_access():
    tok = create_access_token(user_id=7)
    claims = decode_token(tok)
    assert claims["sub"] == "7" and claims["type"] == "access"

def test_refresh_type():
    assert decode_token(create_refresh_token(user_id=7))["type"] == "refresh"

def test_tampered_rejected():
    with pytest.raises(Exception):
        decode_token("not.a.jwt")
```

- [ ] **Step 2: Run → FAIL**.
- [ ] **Step 3: Implement** (append to `security.py`):

```python
import os
from datetime import datetime, timedelta, timezone
from jose import jwt

_SECRET = os.getenv("JWT_SECRET", "dev-insecure-change-me")
_ALG = "HS256"
ACCESS_TTL = timedelta(minutes=30)
REFRESH_TTL = timedelta(days=14)

def _make(user_id: int, ttl: timedelta, kind: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(user_id), "type": kind, "iat": now, "exp": now + ttl}, _SECRET, algorithm=_ALG)

def create_access_token(user_id: int) -> str: return _make(user_id, ACCESS_TTL, "access")
def create_refresh_token(user_id: int) -> str: return _make(user_id, REFRESH_TTL, "refresh")
def decode_token(token: str) -> dict: return jwt.decode(token, _SECRET, algorithms=[_ALG])
```

- [ ] **Step 4: Run → PASS**.
- [ ] **Step 5: Commit** — `git commit -am "feat(auth): JWT access/refresh create + verify"`

### Task 1.4: UserRepository

**Files:** Create `app/backend/repositories/user_repository.py`; Test `tests/auth/test_user_repository.py`

- [ ] **Step 1: Write the failing test** (uses an in-memory SQLite session fixture mirroring existing repo tests — create the engine from `Base.metadata`):

```python
# tests/auth/test_user_repository.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.backend.database.models import Base
from app.backend.repositories.user_repository import UserRepository

@pytest.fixture
def db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng); s = sessionmaker(bind=eng)()
    yield s; s.close()

def test_create_and_get(db):
    repo = UserRepository(db)
    u = repo.create(email="a@x.com", hashed_password="h", full_name="A")
    assert repo.get_by_email("a@x.com").id == u.id
    assert repo.get_by_id(u.id).email == "a@x.com"

def test_email_unique(db):
    repo = UserRepository(db)
    repo.create(email="a@x.com", hashed_password="h")
    with pytest.raises(Exception):
        repo.create(email="a@x.com", hashed_password="h2")

def test_find_or_create_oauth(db):
    repo = UserRepository(db)
    u1 = repo.find_or_create_oauth(provider="google", provider_account_id="g1", email="a@x.com", full_name="A")
    u2 = repo.find_or_create_oauth(provider="google", provider_account_id="g1", email="a@x.com", full_name="A")
    assert u1.id == u2.id  # idempotent
```

- [ ] **Step 2: Run → FAIL**.
- [ ] **Step 3: Implement** `UserRepository` with `create(email, hashed_password=None, full_name=None, is_superuser=False)`, `get_by_email`, `get_by_id`, and `find_or_create_oauth(provider, provider_account_id, email, full_name)` (look up `OAuthAccount`; if absent, find user by email or create one with `hashed_password=None`, then create the `OAuthAccount` link; commit + return the user).
- [ ] **Step 4: Run → PASS**.
- [ ] **Step 5: Commit** — `git commit -am "feat(auth): UserRepository (create/get/find_or_create_oauth)"`

### Task 1.5: Auth Pydantic schemas

**Files:** Create `app/backend/models/auth_schemas.py`; Test `tests/auth/test_auth_schemas.py`

- [ ] **Step 1:** Write a test asserting `RegisterRequest(email,password,full_name?)`, `LoginRequest(email,password)`, `TokenResponse(access_token, token_type="bearer")`, `UserOut(id,email,full_name,is_superuser)` validate as expected (email format enforced via `EmailStr`).
- [ ] **Step 2: Run → FAIL**.
- [ ] **Step 3: Implement** the four models (`UserOut` uses `model_config = ConfigDict(from_attributes=True)`).
- [ ] **Step 4: Run → PASS**.
- [ ] **Step 5: Commit** — `git commit -am "feat(auth): register/login/token/user schemas"`

### Task 1.6: Auth routes + get_current_user + wiring

**Files:** Create `app/backend/auth/dependencies.py`, `app/backend/routes/auth.py`; Modify `app/backend/routes/__init__.py`; Test `tests/auth/test_auth_routes.py`

- [ ] **Step 1: Write the failing test** (FastAPI `TestClient`, app with `auth_router`, in-memory DB via dependency override of `get_db`):

```python
# tests/auth/test_auth_routes.py
def test_register_login_me_flow(client):
    r = client.post("/auth/register", json={"email": "a@x.com", "password": "pw123456", "full_name": "A"})
    assert r.status_code == 201
    tok = r.json()["access_token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert me.status_code == 200 and me.json()["email"] == "a@x.com"

def test_login_bad_password(client):
    client.post("/auth/register", json={"email": "a@x.com", "password": "pw123456"})
    assert client.post("/auth/login", json={"email": "a@x.com", "password": "nope"}).status_code == 401

def test_me_requires_auth(client):
    assert client.get("/auth/me").status_code == 401
```

(Provide a `client` fixture that builds a `FastAPI()` with `auth_router`, overrides `get_db` to the in-memory session, and `Base.metadata.create_all`.)

- [ ] **Step 2: Run → FAIL**.
- [ ] **Step 3: Implement `dependencies.py`:**

```python
from fastapi import Depends, HTTPException, Header
from sqlalchemy.orm import Session
from app.backend.database import get_db
from app.backend.auth.security import decode_token
from app.backend.repositories.user_repository import UserRepository

def get_current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Not authenticated")
    try:
        claims = decode_token(authorization.split(" ", 1)[1])
        if claims.get("type") != "access":
            raise ValueError("wrong token type")
    except Exception:
        raise HTTPException(401, "Invalid or expired token")
    user = UserRepository(db).get_by_id(int(claims["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(401, "User not found or inactive")
    return user
```

- [ ] **Step 4: Implement `routes/auth.py`** — `POST /auth/register` (409 if email exists; hash; create; return `TokenResponse` 201 + set refresh httpOnly cookie), `POST /auth/login` (verify; 401 on bad creds; tokens + cookie), `POST /auth/refresh` (read refresh cookie; verify type=refresh; new access), `POST /auth/logout` (clear cookie), `GET /auth/me` (`Depends(get_current_user)` → `UserOut`). Refresh cookie: `httponly=True, samesite="lax", secure=<env: cookie_secure>`.
- [ ] **Step 5:** Wire in `routes/__init__.py`: `from app.backend.routes.auth import router as auth_router` + `api_router.include_router(auth_router, tags=["auth"])`.
- [ ] **Step 6: Run → PASS**; `pytest tests/auth -q` green; `pytest tests/ -q` no regressions.
- [ ] **Step 7: Commit** — `git commit -am "feat(auth): /auth register/login/refresh/logout/me + get_current_user"`

---

## WAVE 2 — OAuth (Google, GitHub)

### Task 2.1: OAuth client config (sync)

**Files:** Create `app/backend/auth/oauth.py`; Test `tests/auth/test_oauth_config.py`

- [ ] **Step 1:** Test that `get_provider("google")` / `get_provider("github")` return a config object carrying `authorize_url`, `token_url`, `userinfo_url`, `client_id`, `scope`; unknown provider raises `ValueError`. (Client id/secret read from env; test sets dummy env vars.)
- [ ] **Step 2: Run → FAIL**.
- [ ] **Step 3: Implement** `oauth.py` — a `PROVIDERS` dict (google: accounts.google.com endpoints, scope `openid email profile`; github: github.com/login/oauth + api.github.com/user, scope `read:user user:email`), `get_provider(name)`, plus helpers `build_authorize_url(provider, state, redirect_uri)` and **sync** `exchange_code(provider, code, redirect_uri) -> {provider_account_id, email, full_name}` using `authlib.integrations.requests_client.OAuth2Session` (synchronous). For GitHub, fetch `/user` and `/user/emails` to resolve a verified primary email.
- [ ] **Step 4: Run → PASS**.
- [ ] **Step 5: Commit** — `git commit -am "feat(auth): Google/GitHub OAuth client config (sync)"`

### Task 2.2: OAuth routes (authorize + callback)

**Files:** Modify `app/backend/routes/auth.py`; Test `tests/auth/test_oauth_routes.py`

- [ ] **Step 1: Write the failing test** — monkeypatch `oauth.exchange_code` to return a fixed identity; `GET /auth/oauth/google` returns a redirect (302) to the provider with a `state`; `GET /auth/oauth/google/callback?code=x&state=...` (with a matching state cookie) creates/links the user and issues tokens (sets refresh cookie + returns/redirects with access).
- [ ] **Step 2: Run → FAIL**.
- [ ] **Step 3: Implement** — `GET /auth/oauth/{provider}`: generate `state`, set a short-lived `oauth_state` cookie, 302 to `build_authorize_url`. `GET /auth/oauth/{provider}/callback`: validate `state` vs cookie, call `exchange_code`, `UserRepository.find_or_create_oauth(...)`, issue tokens, set refresh cookie, **302-redirect to the frontend** (`FRONTEND_URL` env) with the access token in the URL fragment (SPA reads it on load). Reject mismatched/missing state with 400.
- [ ] **Step 4: Run → PASS**; `pytest tests/auth -q`.
- [ ] **Step 5: Commit** — `git commit -am "feat(auth): Google/GitHub OAuth authorize + callback routes"`

---

## WAVE 3 — Tenancy migration

> Top-level user-owned tables (get `user_id`): `api_keys`, `scanner_configs`, `pipeline_runs`, `pipeline_schedule`, `notification_subscriptions`, `research_reports`, `user_watchlists`, `analyze_flows`, `strategies`, `lab_chat_messages`, `backtests`. Children scope via parent FK (`scan_runs`→`scanner_configs`, `research_trade_plans`→`research_reports`, `notification_deliveries`→`notification_subscriptions`). Global (no `user_id`): `ticker_snapshots`, `analyst_target_snapshots`. Investigate `watchlist_entries` (legacy scanner watchlist) — scope only if user-owned.

### Task 3.1: Add nullable user_id + seed owner + backfill

**Files:** Modify `app/backend/database/models.py` (add `user_id` columns); migration `<sha>_add_user_id_tenancy.py`; Test `tests/auth/test_tenancy_migration.py`

- [ ] **Step 1: Write the failing test** — after `Base.metadata.create_all`, assert each top-level table has a `user_id` column.

```python
def test_user_id_added_to_owned_tables():
    from app.backend.database.models import Base
    owned = {"api_keys","scanner_configs","pipeline_runs","pipeline_schedule",
             "notification_subscriptions","research_reports","user_watchlists",
             "analyze_flows","strategies","lab_chat_messages","backtests"}
    for t in owned:
        cols = {c.name for c in Base.metadata.tables[t].columns}
        assert "user_id" in cols, f"{t} missing user_id"
```

- [ ] **Step 2: Run → FAIL**.
- [ ] **Step 3: Implement (models):** add `user_id = Column(BigInteger().with_variant(Integer(), "sqlite"), ForeignKey("users.id"), nullable=True, index=True)` to each of the 11 top-level models. (`pipeline_schedule` was a singleton id=1 — drop the singleton assumption: add `user_id` unique; the per-user seed/lookup changes in Wave 6.)
- [ ] **Step 4: Author migration** — `upgrade()`:
  1. `op.add_column` `user_id` (nullable) + index on each table (use `batch_alter_table` for SQLite ALTER support).
  2. Seed an owner user if none exists (raw insert into `users`: email from env `SEED_OWNER_EMAIL` default `owner@local`, `is_superuser=1`, `hashed_password` = a hash of a random/env password — or null + must-reset). Capture its id.
  3. `op.execute(f"UPDATE <table> SET user_id = {owner_id} WHERE user_id IS NULL")` for each table.
  `downgrade()` drops the columns. Chains from Wave 1 head.
- [ ] **Step 5: Run → PASS**; `alembic upgrade head` clean (SQLite + the PG smoke from Task 0.3).
- [ ] **Step 6: Commit** — `git commit -am "feat(tenancy): add nullable user_id to owned tables + seed owner + backfill"`

### Task 3.2: Enforce user_id NOT NULL

**Files:** migration `<sha>_user_id_not_null.py`; Modify models (`nullable=False`); Test (extend `test_tenancy_migration.py`)

- [ ] **Step 1:** Test asserting inserting an owned row without `user_id` raises IntegrityError (after migration).
- [ ] **Step 2: Run → FAIL**.
- [ ] **Step 3:** Migration sets each `user_id` NOT NULL (`batch_alter_table().alter_column(nullable=False)`); flip `nullable=False` in models.
- [ ] **Step 4: Run → PASS**; full `alembic upgrade head` clean.
- [ ] **Step 5: Commit** — `git commit -am "feat(tenancy): user_id NOT NULL after backfill"`

---

## WAVE 4 — Scope repositories + routes by user_id

> **Shared pattern (the exemplar in Task 4.1 shows full code; every later task repeats it):**
> 1. Repo methods take `user_id` and add `.filter(Model.user_id == user_id)` to every query; `create` sets `user_id`.
> 2. Routes add `current_user = Depends(get_current_user)` and pass `current_user.id`.
> 3. Single-row get/update/delete returns 404 when the row's `user_id` != caller (never reveal cross-tenant existence).
> 4. Ship an isolation test: user A creates a row; user B gets 404/empty on list/get/update/delete.

### Task 4.1: EXEMPLAR — scope user_watchlists

**Files:** Modify `app/backend/repositories/watchlist_repository.py` (or wherever `user_watchlists` CRUD lives), `app/backend/routes/watchlists.py`; Test `tests/auth/test_isolation_watchlists.py`

- [ ] **Step 1: Write the failing isolation test**

```python
# tests/auth/test_isolation_watchlists.py
def test_watchlist_isolation(client, user_a_token, user_b_token):
    a = client.post("/watchlists", json={"name": "A list"}, headers=auth(user_a_token)).json()
    # B cannot see A's list
    assert all(w["id"] != a["id"] for w in client.get("/watchlists", headers=auth(user_b_token)).json())
    # B cannot fetch / delete A's list
    assert client.get(f"/watchlists/{a['id']}", headers=auth(user_b_token)).status_code == 404
    assert client.delete(f"/watchlists/{a['id']}", headers=auth(user_b_token)).status_code == 404
    # A still can
    assert client.get(f"/watchlists/{a['id']}", headers=auth(user_a_token)).status_code == 200
```

(Add shared fixtures `user_a_token`/`user_b_token`/`auth()` to `tests/auth/conftest.py` — register two users, return their access tokens.)

- [ ] **Step 2: Run → FAIL** (routes ignore the user today).
- [ ] **Step 3: Implement** — thread `user_id` through every `watchlist` repo method (`list`, `get`, `create`, `update`, `add_ticker`, `remove_ticker`, `delete`); each query filters `user_id`; `get`/mutations return None→404 when not owned. Routes inject `current_user` and pass `current_user.id`.
- [ ] **Step 4: Run → PASS**; `pytest tests/auth/test_isolation_watchlists.py tests/ -q` (fix any watchlist tests that now need a user/token).
- [ ] **Step 5: Commit** — `git commit -am "feat(tenancy): scope watchlists by user_id + isolation test"`

### Tasks 4.2 – 4.11: scope the remaining owned resources (repeat the 4.1 pattern)

For each resource below, do the 5 steps from 4.1 — failing isolation test → run → scope repo+routes → run → commit. One task + commit per resource:

- [ ] **4.2 research_reports** (+ `research_trade_plans` via the report FK) — `research_repository.py`, `routes/research.py`. Isolation test incl. the report-delete path.
- [ ] **4.3 screener_presets** — `screener_preset_repository.py`, preset routes in `routes/screener.py`.
- [ ] **4.4 scanner_configs** (+ `scan_runs` via config FK) — `scanner_repository.py`, `routes/scanner.py`.
- [ ] **4.5 pipeline_runs + pipeline_schedule** — `pipeline_repository.py`, `routes/pipeline.py` (schedule becomes per-user — see Wave 6).
- [ ] **4.6 analyze_flows** — `routes/analyze_flows.py` + repo.
- [ ] **4.7 strategies** — lab strategy repo, `routes/lab.py`.
- [ ] **4.8 lab_chat_messages** — lab repo/routes.
- [ ] **4.9 backtests** — backtest repo/routes.
- [ ] **4.10 notification_subscriptions** (+ `notification_deliveries` via FK) — `routes/notifications.py` + repo.
- [ ] **4.11 watchlist_entries** — inspect usage; if user-owned, scope it; if it's a global scanner artifact, leave it and note why in the commit message.

---

## WAVE 5 — Per-user API keys

### Task 5.1: Resolve API keys for the requesting user

**Files:** Modify `app/backend/services/api_key_service.py`, `app/backend/routes/api_keys.py`, and the analyze/scan/refresh call sites that build keys; Test `tests/auth/test_api_keys_per_user.py`

- [ ] **Step 1: Write the failing test** — user A stores a key (`POST /api-keys`), user B's `GET /api-keys` does not include it; `ApiKeyService(db, user_id=A).get_api_keys_dict()` returns A's key, `user_id=B` returns empty.
- [ ] **Step 2: Run → FAIL**.
- [ ] **Step 3: Implement** — `ApiKeyService.__init__(self, db, user_id)`; every repo query filters `user_id`; routes inject `current_user`. Update analyze/scan/snapshot-refresh call sites that construct `ApiKeyService` to pass the acting user's id (request user for HTTP paths; the owning user for cron paths — Wave 6). A user with no LLM key → the analyze/scan path returns a clear `400/422` "add your API key in Settings".
- [ ] **Step 4: Run → PASS**; `pytest tests/ -q`.
- [ ] **Step 5: Commit** — `git commit -am "feat(tenancy): per-user API key storage + resolution"`

---

## WAVE 6 — Per-user opt-in crons

### Task 6.1: Per-user scheduled jobs (snapshot stays global)

**Files:** Modify `app/backend/services/scheduler_service.py`; Test `tests/auth/test_cron_per_user.py`

- [ ] **Step 1: Write the failing test** — mock repos so two users exist, one with `schedule_enabled=True` + keys, one without; assert the preset/research job body runs only for the enabled+keyed user, using that user's keys; assert the snapshot job body is unchanged (global, no user loop).
- [ ] **Step 2: Run → FAIL**.
- [ ] **Step 3: Implement** — snapshot job body unchanged. `_run_preset_job_body` / research / scanner cron bodies iterate users with an enabled schedule **and** required keys (`ApiKeyService(db, user_id)`), running each with that user's keys; skip users without keys (log + continue). Default schedules **off** so nothing auto-spends on a user's keys without opt-in.
- [ ] **Step 4: Run → PASS**; scheduler add_job count assertions updated if changed.
- [ ] **Step 5: Commit** — `git commit -am "feat(tenancy): per-user opt-in scheduled jobs; snapshot stays global"`

---

## WAVE 7 — Frontend auth

### Task 7.1: Auth types + service

**Files:** Create `src/types/auth.ts`, `src/services/auth-service.ts`

- [ ] **Step 1:** Add `User { id; email; full_name; is_superuser }` and `TokenResponse { access_token; token_type }` to `types/auth.ts`.
- [ ] **Step 2:** Implement `auth-service.ts`: `register`, `login`, `refresh` (credentials: 'include' for the cookie), `logout`, `me(token)`, and `oauthUrl(provider)` returning `${API_BASE}/auth/oauth/${provider}`. `API_BASE` from `import.meta.env.VITE_API_URL`.
- [ ] **Step 3:** `tsc --noEmit` clean.
- [ ] **Step 4: Commit** — `git commit -am "feat(auth-fe): auth types + service client"`

### Task 7.2: API client wrapper (token + 401→refresh→retry)

**Files:** Create `src/lib/api-client.ts`; Test by tsc + manual

- [ ] **Step 1:** Implement `apiFetch(path, opts)` that reads the in-memory access token (from the auth context's getter), attaches `Authorization`, and on `401` calls `/auth/refresh` once, stores the new token, and retries; on refresh failure triggers logout.
- [ ] **Step 2:** `tsc --noEmit` clean.
- [ ] **Step 3: Commit** — `git commit -am "feat(auth-fe): api-client with 401 refresh-retry"`

### Task 7.3: AuthProvider context

**Files:** Create `src/contexts/auth-context.tsx`; Modify `src/main.tsx`

- [ ] **Step 1:** `AuthProvider` holds `user`, `accessToken` (in memory), `status` ('loading'|'authed'|'anon'); on mount tries `/auth/refresh` (silent login via cookie) then `me()`; exposes `login`, `register`, `logout`, `loginWithOAuth(provider)`, and a `getToken()` for `api-client`. Also reads an access token from the URL fragment on load (OAuth callback) and clears it.
- [ ] **Step 2:** Wrap in `main.tsx`: `<ThemeProvider><AuthProvider><App/></AuthProvider></ThemeProvider>`.
- [ ] **Step 3:** `tsc --noEmit` clean.
- [ ] **Step 4: Commit** — `git commit -am "feat(auth-fe): AuthProvider context + silent refresh on load"`

### Task 7.4: Login page + protected shell + user menu

**Files:** Create `src/components/auth/login-page.tsx`, `src/components/auth/user-menu.tsx`; Modify `src/App.tsx`, `src/i18n/locales/{en,zh}.json`

- [ ] **Step 1:** `LoginPage` — email+password login/register toggle + "Continue with Google / GitHub" buttons (`window.location.href = authService.oauthUrl(p)`). i18n `auth.*` keys (en+zh).
- [ ] **Step 2:** In `App.tsx`, consume `useAuth()`: `status==='loading'` → spinner; `'anon'` → `<LoginPage/>`; `'authed'` → existing layout. Add `<UserMenu/>` (name + logout) into the layout header.
- [ ] **Step 3:** `tsc --noEmit` clean.
- [ ] **Step 4: Commit** — `git commit -am "feat(auth-fe): login page, OAuth buttons, protected shell, user menu"`

### Task 7.5: Route existing fetches through api-client

**Files:** Modify the existing service modules (`screener-service.ts`, `watchlist-service.ts`, research/scanner/lab/analyze services)

- [ ] **Step 1:** Replace raw `fetch(`${API_BASE}...`)` with `apiFetch(...)` so every request carries auth + refresh-retry. Keep signatures identical.
- [ ] **Step 2:** `tsc --noEmit` clean.
- [ ] **Step 3: Commit** — `git commit -am "feat(auth-fe): route all API calls through authenticated api-client"`

---

## WAVE 8 — Hardening + final verification

### Task 8.1: Env-driven CORS + JWT secret check

**Files:** Modify `app/backend/main.py`

- [ ] **Step 1:** CORS `allow_origins` from `FRONTEND_ORIGINS` env (comma-split; default the two localhost URLs). On startup, if `JWT_SECRET` is unset, log a loud WARNING (dev default in use).
- [ ] **Step 2:** `pytest tests/ -q` green.
- [ ] **Step 3: Commit** — `git commit -am "chore(auth): env-driven CORS origins + JWT secret startup check"`

### Task 8.2: Final isolation sweep + suite green + tsc

**Files:** Test `tests/auth/test_isolation_sweep.py`; `progress.md`

- [ ] **Step 1:** A parametrized sweep: for every owned resource's list endpoint, user B never sees user A's rows. Add any endpoint missed in Wave 4.
- [ ] **Step 2:** `pytest tests/ v2/scanner/ -q` green; from `app/frontend/` `node node_modules/typescript/bin/tsc --noEmit` clean.
- [ ] **Step 3:** Append a wrap-up entry to `progress.md`.
- [ ] **Step 4: Commit** — `git commit -am "test(tenancy): cross-tenant isolation sweep + final verification"`

---

## Self-review notes (plan ↔ spec coverage)

- Auth (email+pw + Google/GitHub, JWT, get_current_user): Waves 1–2. ✓
- Per-user data isolation across the 11 owned tables + children + globals: Waves 3–4. ✓
- Per-user API keys: Wave 5. ✓
- Per-user opt-in crons, snapshot global: Wave 6. ✓
- SQLite→Postgres: Wave 0 (+ migrations verified on PG). ✓
- Frontend auth (context, login, OAuth, protected shell, fetch wrapper): Wave 7. ✓
- Security (httpOnly refresh cookie, OAuth state, env CORS/secret, isolation tests): Waves 1, 2, 8 + every Wave-4 task. ✓
- Out of scope (deployment, payments, email verification): not planned here, per spec. ✓
