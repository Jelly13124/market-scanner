# Public deployment (Fly.io) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.
> Steps use `- [ ]`. Fresh implementer per task; two-stage review. The CODE tasks are
> TDD; the CONFIG tasks (Dockerfile/fly.toml) are verified by `docker build` + a local
> run. The actual `fly deploy` is a USER step (I can't run it — it needs the user's Fly
> account + domain); the plan produces every artifact + the runbook for it.

**Goal:** Make the multi-tenant app deployable to Fly.io as ONE app serving the API +
the built frontend at one origin, with email verification + rate limiting for the
semi-public surface, SQLite on a Fly Volume, and a runbook the user follows to deploy.

**Architecture:** Single FastAPI app: API routers at root (unchanged — keeps all tests
green) + the built frontend served via StaticFiles + an SPA catch-all registered LAST.
Multi-stage Docker image (vite build → python). `fly.toml` pins one machine with a
volume; entrypoint runs `alembic upgrade head` (on the machine, where the volume is
mounted) then uvicorn.

**Tech stack:** FastAPI, vite/React build, Docker, Fly.io, slowapi (rate limit), Resend
(email verification — already wired), Fernet (`APP_ENCRYPTION_KEY` from Phase 1).

**Spec:** `docs/superpowers/specs/2026-06-01-public-deployment-design.md`

---

## Constraints (paste into every implementer prompt)

- Python `C:\Users\Jerry\anaconda3\python.exe`; tests `-m pytest`; repo root +
  `PYTHONPATH=.`. Frontend typecheck: `cd app/frontend && node node_modules/typescript/bin/tsc --noEmit`.
- Branch **`feature/per-user-keys`** (the deploy-ready line: multi-tenant + Phase-1 key
  wiring). Commit per task; conventional message; **NO Co-Authored-By; never --no-verify**.
  Explicit `git add <paths>` — never `-A`, never stage `.claude/settings.local.json` or
  `scanner_eval/*.csv` (a background job writes those). Black hook → re-add + re-commit.
- All subagents **opus**.
- **Stay on SQLite.** Single instance. Additive migrations only (chain from current head).
- Keep the existing tests GREEN (1113 passed). The single-origin approach keeps API at
  root specifically so route tests don't churn.

---

## Wave A — Single-origin app serving

### Task A1: serve the built SPA from FastAPI (API stays at root)

**Files:** Modify `app/backend/main.py`; Test `tests/test_spa_serving.py` (new).

**Approach (deliberate):** keep API routers at root (`/auth`, `/research`, … — no `/api`
prefix, so the 1113 tests + the frontend's `VITE_API_URL` usage are unchanged). After
`app.include_router(api_router)`, mount the frontend: a StaticFiles for the build's
assets, and a catch-all `GET /{full_path:path}` registered LAST that returns
`index.html` for any unmatched path (SPA client-side routing). API routes (specific)
always win; only unmatched paths fall to the SPA. Frontend `VITE_API_URL=https://<domain>`
(same origin). (Alternative `/api`-prefix rejected: it would break every root-path test.)

- [ ] **Step 1 — failing test:**
```python
def test_spa_served_at_root(monkeypatch, tmp_path):
    # point the app at a fake dist dir with index.html + assets/app.js
    # GET "/" → 200 text/html containing the index marker
    # GET "/some/client/route" → 200 index.html (SPA fallback)
    # GET "/health" → still the API health route (NOT index.html)  ← API not shadowed
    # GET "/assets/app.js" → the static asset
```
- [ ] **Step 2** — FAIL.
- [ ] **Step 3 — implement.** In `main.py`, behind a `FRONTEND_DIST` env (default
  `app/frontend/dist`): if the dir exists, `app.mount("/assets", StaticFiles(directory=
  dist/"assets"))` and add a catch-all route (registered after all routers) returning
  `FileResponse(dist/"index.html")` for GET requests whose path isn't an API route.
  Guard: if `FRONTEND_DIST` doesn't exist (dev/tests without a build), skip the mount so
  nothing breaks. Ensure the catch-all is added AFTER `include_router(api_router)`.
- [ ] **Step 4** — PASS + run a slice of existing route tests (`tests/ -k "auth or health" -q`) to confirm API routes still resolve (not shadowed).
- [ ] **Step 5 — commit.** `feat(deploy): serve the built SPA from FastAPI (single origin, API at root)`

---

## Wave B — Abuse protection (semi-public)

### Task B1: email verification for password registration

**Files:** Modify `app/backend/database/models.py` (User.is_verified) + a migration +
`app/backend/routes/auth.py` + `app/backend/auth/` (token + email send via the existing
Resend `EmailHandler`); Test `tests/auth/test_email_verification.py` (new).

Context: OAuth logins already arrive `email_verified` (oauth.py) — those users are
auto-verified. ONLY password registration needs verification.

- [ ] **Step 1 — failing tests:** (a) register (password) → user `is_verified=False`, a
  verification email is sent (mock the Resend handler, assert called with a tokened
  link); (b) `GET /auth/verify?token=<valid>` → sets `is_verified=True`, redirects/200;
  (c) with `REQUIRE_EMAIL_VERIFICATION=true`, an unverified user calling a gated endpoint
  (or login) → 403 "verify your email"; (d) an OAuth user is `is_verified=True` without
  the email step.
- [ ] **Step 2** — FAIL.
- [ ] **Step 3 — implement.** Add `is_verified: bool` (server_default false) to `User` +
  an additive migration (down_revision = current head; bool server_default
  `text("false")`). On password register: create user `is_verified=False`, generate a
  signed token (reuse the JWT helper with a `type="verify"` + short TTL, or a random
  token row), send an email via `EmailHandler` with `https://<domain>/auth/verify?token=…`.
  Add `GET /auth/verify`. Gate behind `REQUIRE_EMAIL_VERIFICATION` env (default false in
  dev so existing tests pass; true in prod): a dependency/check that rejects unverified
  users on protected routes (or at login). OAuth path sets `is_verified=True`.
- [ ] **Step 4** — PASS; full `tests/auth/ -q` green (existing auth tests run with
  `REQUIRE_EMAIL_VERIFICATION` unset → unaffected).
- [ ] **Step 5 — commit.** `feat(deploy): email verification for password signups (Resend), OAuth auto-verified`

### Task B2: rate limiting

**Files:** `pyproject.toml` (slowapi), `app/backend/main.py` (limiter + handler), the
auth/analyze routes (decorators or a middleware); Test `tests/test_rate_limit.py` (new).

- [ ] **Step 1 — failing test:** hammer `/auth/login` past the limit → a `429` response;
  a normal request rate → 200. (Use a low test limit via env/override.)
- [ ] **Step 2** — FAIL.
- [ ] **Step 3 — implement.** Add `slowapi`; create a `Limiter(key_func=get_remote_address)`
  in `main.py`, register the `_rate_limit_exceeded_handler`, add `SlowAPIMiddleware`.
  Apply tight limits to `/auth/login` + `/auth/register` (e.g. `@limiter.limit("10/minute")`)
  and a modest limit to the analyze/scan trigger endpoints. Limits configurable via env
  (so tests can set a tiny limit). Keyed by IP (and user where available).
- [ ] **Step 4** — PASS; confirm normal tests aren't tripped (limits high enough or
  disabled when the env knob says so).
- [ ] **Step 5 — commit.** `feat(deploy): IP rate limiting on auth + analyze (slowapi)`

---

## Wave C — Containerization

### Task C1: multi-stage Dockerfile + entrypoint

**Files:** Create `Dockerfile` (repo root, or adapt `docker/Dockerfile`),
`docker/entrypoint.sh`; verify with `docker build`.

- [ ] **Step 1 — write the Dockerfile.** Multi-stage:
  - Stage `frontend`: `node:20`, `COPY app/frontend`, `npm ci`, `VITE_API_URL` build-arg,
    `npm run build` → `/app/frontend/dist`.
  - Stage `backend`: `python:3.13-slim`, install system deps + the Python deps (pip from
    `requirements`/poetry-export — match how the repo installs), `COPY` the app, `COPY
    --from=frontend /app/frontend/dist ./app/frontend/dist`, `EXPOSE 8000`, entrypoint.
- [ ] **Step 2 — `docker/entrypoint.sh`:** `set -e; alembic upgrade head; exec uvicorn
  app.backend.main:app --host 0.0.0.0 --port 8000` (no `--reload`). Runs ON the machine
  (where the Fly volume is mounted) — NOT a Fly `release_command` (that machine has no
  volume). `alembic` runs from the right dir with `PYTHONPATH` set.
- [ ] **Step 3 — verify:** `docker build -t app-test .` succeeds (build-arg
  `VITE_API_URL=http://localhost:8000`). If Docker isn't available in this env, do a
  dry static review + `hadolint`-style sanity, and note "build to be run by the user".
- [ ] **Step 4 — commit.** `feat(deploy): multi-stage Dockerfile (vite build + python) + entrypoint (migrate→uvicorn)`

### Task C2: fly.toml

**Files:** Create `fly.toml`.

- [ ] **Step 1 — write `fly.toml`:**
```toml
app = "<set-on-launch>"
primary_region = "<near users>"
[build]
  dockerfile = "Dockerfile"
  [build.args]
    VITE_API_URL = "https://<your-domain>"   # rebuilt if domain changes
[env]
  DATABASE_URL = "sqlite:////data/app.db"
  REQUIRE_EMAIL_VERIFICATION = "true"
  FRONTEND_DIST = "/app/app/frontend/dist"
[[mounts]]
  source = "data"
  destination = "/data"
[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = false
  min_machines_running = 1
  [[http_service.checks]]
    path = "/health"
    interval = "30s"
    timeout = "5s"
```
- [ ] **Step 2 — verify** `fly.toml` parses (`fly config validate` if fly CLI present;
  else a TOML lint). Confirm secrets are NOT in it (they go via `fly secrets`).
- [ ] **Step 3 — commit.** `feat(deploy): fly.toml (one machine + volume, force_https, /health check)`

---

## Wave D — Runbook + local smoke

### Task D1: `docs/DEPLOY.md`

- [ ] Write the full runbook the USER executes (they have the Fly account + domain):
  1. `fly launch --no-deploy` (name, region). 2. `fly volumes create data --size 3`.
  3. `fly secrets set JWT_SECRET=$(openssl rand -hex 32) APP_ENCRYPTION_KEY=$(python -c
  'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')
  RESEND_API_KEY=… RESEND_FROM_EMAIL=… EODHD_API_KEY=… FINNHUB_API_KEY=…`. 4. `fly deploy`.
  5. `fly certs add <domain>` + the DNS record. 6. smoke: register → verify email → add
  LLM key → run analysis. 7. updates `fly deploy`; scale `fly scale memory 4096`; logs
  `fly logs`; backups (Fly daily volume snapshots + optional litestream).
- [ ] **Commit.** `docs(deploy): Fly.io deployment runbook`

### Task D2: local docker smoke (verification)

- [ ] If Docker is available: `docker build` the image, run it with a local volume +
  the required env (a throwaway `JWT_SECRET`/`APP_ENCRYPTION_KEY`), hit `/health`, load
  `/` (SPA), register a user, confirm `alembic upgrade head` created the schema on the
  fresh volume. Document the result. If Docker isn't available here, mark this as a
  user-run check in `DEPLOY.md` and verify the pieces (entrypoint script, migration
  command) statically.
- [ ] **Commit** any fixups. Final: full backend suite still green + frontend `tsc` clean.

---

## NOT in this plan (user-executed)

- The actual `fly launch/deploy/certs`, DNS, `fly secrets` — the user runs these per
  `DEPLOY.md` (they require the Fly account + domain).
- Merging the multi-tenant + Phase-1 line to `main` — the user's call at deploy time.
- Buying the domain.

## Self-review (done)

- **Spec coverage:** single-origin serving (A1), email verify (B1), rate limit (B2),
  Dockerfile+entrypoint (C1), fly.toml (C2), runbook (D1), smoke (D2) — every spec
  component mapped; the migration-in-entrypoint gotcha + one-machine/volume pins are
  captured. ✓
- **Test stability:** API stays at root → the 1113 tests don't churn; new features gated
  behind env defaults that keep existing tests green. ✓
- **No placeholders:** concrete files + the fly.toml/entrypoint content inline; the
  user-only deploy steps are explicitly carved out. ✓
