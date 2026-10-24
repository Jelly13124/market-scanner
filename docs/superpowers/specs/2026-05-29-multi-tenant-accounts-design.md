# Multi-Tenant Accounts — design spec

## Context

Quant Lab is today a **single-user local tool**: one SQLite DB, one global set
of watchlists / reports / presets / scanner configs that the whole UI reads and
writes. There is **no concept of a user** and **no authentication** anywhere
(CORS is locked to localhost; the `api_keys` table stores *data-provider* keys,
not logins).

The goal is to let friends use it over the public internet, each with their own
account and their own data. Per the brainstorming session this decomposed into
**two sequential projects**:

1. **Multi-tenant accounts (THIS spec)** — auth + per-user data isolation +
   per-user API keys. The bulk of the work.
2. **Public deployment (separate spec, later)** — VPS + Docker + Caddy + TLS.
   Not started until this lands; nothing goes public before then.

## Goal

Turn the single-user app into a multi-tenant one: users register / log in
(email+password **or** Google/GitHub OAuth), and each user sees and edits only
their own watchlists, reports, presets, scanner configs, strategies, etc., using
their own API keys. Shared market data (snapshots, analyst targets) stays global.

## Decisions (locked in brainstorming)

| Decision | Choice |
|---|---|
| Sequencing | Auth-first; nothing public until this is done |
| Login methods | Email+password **and** Google + GitHub OAuth |
| Registration | Self-service signup (option to add an allowlist before going public) |
| Tenancy | Per-user data; market data (ticker_snapshots, analyst_target_snapshots) shared/global |
| API keys / cost | **Each user brings their own keys** — host never pays; no quota system needed |
| Auth implementation | **Hand-rolled** with `passlib[bcrypt]` + `python-jose` + `authlib` (fits the sync codebase) |
| Database | **Stay on SQLite** with WAL + busy_timeout (fine for a few friends); Postgres optional later via `DATABASE_URL`, zero code change [revised 2026-05-29] |
| Crons | Per-user **opt-in**; snapshot build stays global |

Rejected: `fastapi-users` (async-first, fights the sync codebase); managed auth
(Clerk/Auth0 — vendor + cost, overkill); shared keys + quotas (chose per-user keys instead).

## Architecture

### 1. Auth & accounts

**Libraries (all sync-friendly):** `passlib[bcrypt]` for password hashing,
`python-jose[cryptography]` for JWTs, `authlib` for the Google/GitHub OAuth
authorization-code exchange (done synchronously via authlib's requests client,
so all routes stay sync `def`).

**New tables:**
- `users` — `id` (BigInteger w/ sqlite Integer variant), `email` (unique,
  citext/lower), `hashed_password` (nullable — null for OAuth-only accounts),
  `full_name`, `is_active` (default true), `is_superuser` (default false — the
  backfill owner), `created_at`.
- `oauth_accounts` — `id`, `user_id` FK, `provider` ('google'|'github'),
  `provider_account_id`, `email`, `created_at`; unique(`provider`,
  `provider_account_id`). Lets one user link both Google and GitHub.

**Tokens:** short-lived **access JWT** (~30 min) sent as `Authorization: Bearer`;
long-lived **refresh token** (~14 days) stored in an **httpOnly cookie** scoped
to `/auth/refresh` (XSS-safe; access token kept in memory client-side).

**Routes** (`app/backend/routes/auth.py`):
- `POST /auth/register` (email, password, name) → creates user, returns tokens.
- `POST /auth/login` (email, password) → verifies, returns tokens.
- `POST /auth/refresh` → new access token from the refresh cookie.
- `POST /auth/logout` → clears the refresh cookie.
- `GET /auth/me` → current user profile.
- `GET /auth/oauth/{provider}` → redirect to Google/GitHub consent.
- `GET /auth/oauth/{provider}/callback` → exchange code, find-or-create user +
  oauth_account, issue tokens. (Find-or-create matches on verified email so a
  user who signed up with a password can also link Google.)

**Dependency:** `get_current_user(token) -> User` — decodes/validates the access
JWT, loads the user, checks `is_active`. Injected into every protected route.
A variant `get_current_user_optional` for routes that are public-readable if any.

**Frontend:**
- `login` / `register` page (email+password form + "Continue with Google /
  GitHub" buttons).
- An **auth context** (`useAuth`) holding the current user + access token (in
  memory), with `login/register/logout/refresh`.
- A **fetch/axios wrapper** that attaches the access token and, on `401`,
  transparently calls `/auth/refresh` once then retries (logout on failure).
- A **protected app shell** — unauthenticated users are redirected to `/login`;
  the existing tabbed UI renders only when authenticated.
- A small user menu (name + logout) in the layout header.

### 2. Data isolation (tenancy) — the bulk of the work

Add a `user_id` FK (+ index) to the **top-level user-owned tables**; child tables
inherit ownership through their parent FK (queries scope via a join, no extra
column):

**Top-level (get `user_id`):** `api_keys`, `scanner_configs`, `pipeline_schedule`,
`pipeline_runs`, `notification_subscriptions`, `research_reports`,
`user_watchlists`, `analyze_flows`, `strategies`, `lab_chat_messages`,
`backtests`. (`watchlist_entries` reviewed during implementation — likely the
legacy scanner watchlist; scope or leave per its actual use.)

**Children (ownership via parent FK, no `user_id`):** `scan_runs`
(→scanner_configs), `research_trade_plans` (→research_reports),
`notification_deliveries` (→notification_subscriptions).

**Global / shared (NO `user_id`):** `ticker_snapshots`, `analyst_target_snapshots`,
detector results — market data, identical for everyone.

**Migration & backfill (additive, non-destructive):**
1. Alembic migration adds **nullable** `user_id` columns + indexes.
2. Seed a superuser account = the host (current data owner).
3. Backfill every existing row's `user_id` to the seed user.
4. A follow-up migration sets `user_id` NOT NULL once backfilled.

**Query scoping (mechanical, wide surface):** every repository method that
reads/writes a user-owned table gains a `user_id` parameter and filters by it;
every route resolves `current_user` and passes `current_user.id`. This touches
nearly all CRUD routes (watchlists, reports, presets, scanner, pipeline, lab,
backtests, notifications) — the largest single chunk of the project.

### 3. Per-user API keys

`api_keys` gains `user_id`. `ApiKeyService` is constructed with a `user_id` and
resolves keys for that user only. The analyze / scan / refresh code paths read
the **requesting user's** keys. The existing Settings → API Keys UI becomes
per-user automatically. A user with no LLM key gets a clear "add your API key in
Settings" message instead of an opaque failure.

### 4. Crons in a multi-user world

- **Snapshot build** stays **global** (yfinance, no key needed) — one nightly job
  for everyone.
- **Scanner / research / preset crons** become **per-user opt-in**: the job
  iterates users who enabled a schedule **and** have the required keys, running
  each with that user's stored keys; users without keys are skipped. This avoids
  surprise spend and respects per-user-keys. Manual buttons (Analyze, "更新数据")
  cover everyone else.

### 5. Database: SQLite → Postgres

- `connection.py` reads `DATABASE_URL` from env (default a local Postgres for
  dev); driver `psycopg`/`psycopg2`.
- Verify all existing Alembic migrations apply cleanly on Postgres (the
  `BigInteger().with_variant(Integer, "sqlite")` PKs use native BigInteger
  autoincrement on PG; `JSON` columns map to JSONB; `Numeric`/`Date`/`DateTime`
  unchanged). Fix any SQLite-only DDL found.
- Fresh Postgres DB built by `alembic upgrade head`. Existing dev data does **not**
  need migrating — snapshots rebuild via cron/button; the user's old reports were
  already cleared. (If any data must move, a one-off export/import script.)
- Local dev: a Postgres container (or local install); `.env` gets `DATABASE_URL`.

## Security considerations

- Passwords hashed with bcrypt; never logged. JWT secret in `.env` (gitignored).
- Refresh token httpOnly + `Secure` + `SameSite=Lax`; access token short-lived,
  in memory (not localStorage) to limit XSS blast radius.
- OAuth `state` parameter validated to prevent CSRF on the callback.
- CORS updated from localhost-only to the configured frontend origin (env-driven).
- Every user-owned query MUST filter by `user_id` — a missing filter is a
  cross-tenant data leak. Tests assert isolation (user A cannot read/modify
  user B's rows).
- API keys remain encrypted-at-rest as today (or add encryption if not) and are
  never returned in full to the client.

## Testing strategy

- **Auth unit tests:** register/login/refresh/logout happy + failure paths;
  password hashing; JWT issue/verify/expiry; OAuth find-or-create (mock the
  provider token + userinfo).
- **Tenancy isolation tests (load-bearing):** for each user-owned resource,
  user A creating a row and user B being unable to list/read/update/delete it
  (404/403). This is the most important test class.
- **Per-user key resolution:** analyze/scan uses the requesting user's keys
  (mocked); no-key path returns the friendly error.
- **Migration tests:** backfill assigns existing rows to the seed user; NOT NULL
  holds afterward; runs on Postgres.
- **Frontend:** auth context + protected-route redirect; 401→refresh→retry in
  the fetch wrapper; `tsc --noEmit` clean.

## Rollout / sequencing within this project

1. DB swap to Postgres + confirm migrations apply (foundation).
2. `users` + `oauth_accounts` models + auth service (hashing, JWT) + routes +
   `get_current_user`.
3. OAuth (Google, GitHub) via authlib.
4. Tenancy migration (add `user_id`, seed owner, backfill, NOT NULL).
5. Scope repositories + routes by `user_id` (the big mechanical wave).
6. Per-user API keys.
7. Per-user opt-in crons.
8. Frontend: auth context, login/register, OAuth buttons, protected shell, fetch
   wrapper, user menu; per-user Settings.
9. Isolation + auth test suite; full-suite green; tsc clean.

## Out of scope (this project)

- The VPS deployment itself (separate spec: Docker + Caddy + TLS + secrets).
- Payments / usage quotas (N/A — per-user keys).
- Email verification + password reset emails (optional; can fold into the deploy
  phase when an email service exists). v1 allows login immediately after signup.
- Org/team accounts, sharing between users, roles beyond user/superuser.
- Real-time multi-user features (presence, collaboration).

## Risks

1. **Tenancy scoping is wide** — every user-owned route/repo must filter by
   `user_id`; a single miss is a data leak. Mitigation: the isolation test class
   above, applied per resource; grep for unscoped queries.
2. **Postgres migration** — existing migrations were authored/run on SQLite;
   some may need fixes to apply on PG. Mitigation: run the full chain on a fresh
   PG early (step 1) before building on top.
3. **Sync OAuth** — keep the OAuth code-exchange synchronous (authlib requests
   client) to avoid introducing an async engine; verify provider callback URLs
   work behind the eventual reverse proxy (revisit in the deploy spec).
4. **Background threads + Postgres sessions** — the analyze/refresh threads must
   each open their own Postgres session (as they do today with SQLite); confirm
   connection-pool sizing so concurrent users + threads don't exhaust it.
5. **Scope/time** — this is multi-week. The rollout order keeps each step
   shippable/testable; the plan phase will break it into bite-sized tasks.
