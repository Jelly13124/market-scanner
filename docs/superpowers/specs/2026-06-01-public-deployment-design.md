# Public deployment — Fly.io (semi-public)

**Status:** design 2026-06-01, brainstormed interactively; platform = **Fly.io**
(user pick). For review → writing-plans → implementation. This is **Phase 2**;
**Phase 1 (per-user API key wiring) is a hard prerequisite** — sibling spec
`2026-06-01-per-user-api-key-wiring-design.md`. Do NOT deploy publicly until users
bring their own keys.

## Goal

Put the multi-tenant app on the public internet for **semi-public** use (open
registration + email verification + rate limiting) on **Fly.io**, one app serving
both API and frontend at one origin, automatic HTTPS, SQLite on a Fly Volume. Host
cost ≈ **$12/mo** (Fly shared-cpu-1x 2 GB) + volume (~$0.50/mo) + domain (~$10/yr);
LLM/data usage = $0 to host (per-user keys).

## Locked decisions

1. **Per-user keys** — host pays $0 for usage (Phase 1 prerequisite).
2. **Semi-public** — open registration + **email verification** (Resend) + **rate
   limiting** + optional invite codes.
3. **Fly.io**, **shared-cpu-1x / 2 GB** to start. A scanner scan spikes to ~1 GB; if
   the nightly scan OOMs, `fly scale memory 4096` (or cap scan concurrency). One
   machine only (SQLite).
4. **Domain** — buy one (~$10/yr); `fly certs add` for auto Let's Encrypt TLS.
5. **Stay on SQLite** (standing decision) — on a **Fly Volume**.

## Architecture

```
        yourapp.com  (fly certs → auto Let's Encrypt;  appname.fly.dev also works)
              │  Fly proxy (TLS termination, HTTP/2)
        ┌─────▼──────────────────────────┐  ONE Fly app, ONE machine
        │  uvicorn (app.backend.main:app) │   ├─ API routers under /api/*
        │                                  │   ├─ built frontend (vite) served at /
        │  APScheduler runs in-process     │   └─ SPA fallback → index.html
        └──────────────┬──────────────────┘
                 Fly Volume  /data  →  SQLite app.db (WAL + busy_timeout)
```

**One app, one origin.** API routers get an `/api` prefix; the built frontend is
served at `/` by the same FastAPI app (StaticFiles + SPA catch-all). No CORS, no
separate frontend host, no Caddy/nginx. `min_machines_running=1` +
`auto_stop_machines=false` → the single machine stays up so APScheduler + the
SQLite volume are always available (Fly's autoscale + SQLite would diverge — pin to
ONE machine).

## Components / files (create or adapt)

| File | Purpose |
|---|---|
| `Dockerfile` (adapt `docker/Dockerfile`) | multi-stage: (1) `node` stage runs `vite build` (with `VITE_API_URL=<prod-url>/api`) → `dist`; (2) python stage installs backend deps, copies `dist` into the image, runs the entrypoint. |
| `fly.toml` | app config: `[build]` Dockerfile; `[[mounts]] source="data" destination="/data"`; `[http_service]` internal_port=8000, `force_https=true`, `auto_stop_machines=false`, `min_machines_running=1`; `[env]` non-secret vars; a `[checks]`/health check on `/health`. |
| `docker/entrypoint.sh` | runs `alembic upgrade head` **on the machine** (the volume is mounted here — NOT in `release_command`, whose machine has no volume), then `exec uvicorn app.backend.main:app --host 0.0.0.0 --port 8000` (no `--reload`). |
| `app/backend/main.py` (edit) | (a) add `/api` prefix to the API routers (or a sub-app), (b) mount the built frontend `dist` as StaticFiles at `/` with an SPA catch-all returning `index.html`, (c) ensure `/health` exists. |
| `docs/DEPLOY.md` | Fly runbook (launch, volume, secrets, deploy, certs, scale, backups). |

## Production configuration

- **Fly secrets** (`fly secrets set ...` — injected as env, never in the image):
  - `JWT_SECRET` = `openssl rand -hex 32` (NOT the dev default).
  - `RESEND_API_KEY` + `RESEND_FROM_EMAIL` (email verification + notifications).
  - Host **market-data** keys for the shared snapshot/crons: `EODHD_API_KEY`,
    `FINNHUB_API_KEY`, (`FINANCIAL_DATASETS_API_KEY`). NO host LLM keys needed
    (per-user).
  - `APP_ENCRYPTION_KEY` (Fernet) — for encrypting stored user keys at rest (Phase 1
    security item).
- **`[env]` in fly.toml** (non-secret): `DATABASE_URL=sqlite:////data/app.db`,
  `REGISTRATION_OPEN=true`, `REQUIRE_EMAIL_VERIFICATION=true`, rate-limit knobs.
- **Frontend build arg** `VITE_API_URL=https://<your-domain>/api` (absolute, same
  origin in prod). NOTE: the services do `VITE_API_URL || 'http://localhost:8000'`,
  so an EMPTY value would wrongly fall back to localhost — must be the real
  non-empty prod URL. Rebuild if the domain changes.

## Auth on a public surface

- Same-origin (frontend + API on one Fly app) → the existing **localStorage
  access-token** flow works as-is (the dev cross-origin limitation is gone).
  **Default: keep it** (minimal change); note httpOnly+Secure+SameSite refresh
  cookie as a fast-follow hardening (now possible same-origin).
- HTTPS enforced by Fly (`force_https`). Strong `JWT_SECRET`; 30-min access TTL +
  refresh rotation (already).

## Abuse protection (semi-public)

1. **Email verification** on register — issue a token, email via Resend, gate
   use until verified. (Confirm whether the multi-tenant auth already stubs this;
   if not, add a `verification_token` + `/auth/verify` + the email.)
2. **Rate limiting** — `slowapi` (or middleware) keyed by IP + user; tight on
   `/api/auth/*`, modest on analyze/scan; cap concurrent scans (protect the 2 GB
   machine).
3. **Optional invite codes** — config flag, off by default.

## SQLite on Fly

- WAL + `busy_timeout=30s` already set. **One machine** with the volume (no
  horizontal scale). Migrations run in the **entrypoint** (the release-command
  machine has no volume — a Fly gotcha; running migrations there would hit a
  different/empty DB).
- **Backups:** Fly Volumes have automatic daily snapshots (~5-day retention) — on by
  default. Add a nightly in-app `.backup` to `/data/backups/` and/or **litestream**
  to S3/Cloudflare R2 for continuous SQLite backup (recommended for a public surface).
- `DATABASE_URL` env keeps a future Postgres swap a 1-var change if scale demands.

## Prerequisites (must land before deploy)

1. **Phase 1 — per-user key wiring + encrypt keys at rest** (sibling spec).
2. **Multi-tenant work merged to `main`** (or deploy from the multi-tenant line) —
   `main` lacks the per-user models/auth. Confirm + merge.

## Ops runbook (in `docs/DEPLOY.md`)

1. `fly launch --no-deploy` (generates `fly.toml`; pick a region near users; app name).
2. `fly volumes create data --size 3 --region <r>` (SQLite lives here).
3. `fly secrets set JWT_SECRET=... RESEND_API_KEY=... EODHD_API_KEY=... APP_ENCRYPTION_KEY=...`.
4. `fly deploy` (builds the multi-stage image; entrypoint runs `alembic upgrade head` then uvicorn).
5. `fly certs add yourapp.com` + set the DNS record Fly prints (A/AAAA or CNAME). Wait for the cert.
6. Verify HTTPS, register → verify email → add LLM key → run an analysis (bills the user's key).
7. Updates: `fly deploy`. Scale RAM if scans OOM: `fly scale memory 4096`. Logs: `fly logs`.

## Testing / verification

- Local: `docker build` + run the image with a local volume + `tls internal`/plain
  HTTP → smoke the full single-origin flow (SPA at `/`, API at `/api`).
- Fresh-volume migration: a brand-new volume → entrypoint `alembic upgrade head`
  creates the schema cleanly.
- `/health` returns 200 (Fly health check + uptime monitor).
- A `docs/DEPLOY.md` checklist.

## Decisions (defaulted — confirm in review)

1. **Fly shared-cpu-1x / 2 GB** to start; `fly scale memory 4096` if the nightly
   scan OOMs (or reduce scan concurrency).
2. **Single Fly app, API under `/api`, SPA served by FastAPI** at `/`
   (`VITE_API_URL=https://domain/api`).
3. **Migrations in the entrypoint** (NOT `release_command` — volume gotcha).
4. Email verification + rate limiting ON; invite codes OFF by default.
5. SQLite on a Fly Volume; Fly daily snapshots + (recommended) litestream to R2.
6. Keep localStorage access-token auth; cookie hardening = fast follow.

## Out of scope

- Horizontal scaling / Postgres / multi-region.
- Per-user verified sender domains.
- The per-user-key WIRING itself (Phase 1, sibling spec).
